#!/usr/bin/python

"CS244 Assignment 3: Hedera"

from mininet.topo import Topo
from mininet.net import Mininet
from mininet.log import lg, output
from mininet.node import CPULimitedHost, RemoteController
from mininet.link import TCLink
from mininet.util import irange, custom, quietRun, dumpNetConnections
from mininet.cli import CLI

from ripl.dctopo import FatTreeTopo

from time import sleep, time
from multiprocessing import Process
from subprocess import Popen
import random

import argparse

import sys
import os
import signal
from util.monitor import monitor_devs_ng

parser = argparse.ArgumentParser(description="Hedera tests")
parser.add_argument('--bw', '-b',
                    type=float,
                    help="Bandwidth of network links",
                    required=True)

parser.add_argument('--dir', '-d',
                    help="Directory to store outputs",
                    default="results")

parser.add_argument('-k',
                    type=int,
                    help=("Number of ports per switch in FatTree."
                    "Must be >= 1"),
                    required=True)

parser.add_argument('--time', '-t',
                    dest="time",
                    type=int,
                    help="Duration of the experiment.",
                    default=60)

parser.add_argument('--iperf',
                    dest="iperf",
                    help="Path to custom iperf",
                    required=True)

parser.add_argument('--traffic',
                    dest="traffic",
                    help="Traffic matrix to simulate",
                    default="stride,1")

parser.add_argument('--seed',
                    dest="seed",
                    help="Random number generator seed",
                    type=int)

parser.add_argument('--controller',
                    dest="controller",
                    help="Controller shell command")

parser.add_argument('--control',
                    dest="control",
                    help="Run control network",
                    default=False,
                    action="store_true")

parser.add_argument('--flowsPerHost',
                    dest="fph",
                    type=int,
                    help="Only use this parameter with random traffic pattern",
                    default=1)

# Export parameters
args = parser.parse_args()

assert args.controller or args.control

IPERF_PATH = args.iperf
assert(os.path.exists(IPERF_PATH))

if not os.path.exists(args.dir):
  os.makedirs(args.dir)

lg.setLogLevel('info')

# Control network
class NonblockingFatTreeTopo(Topo):
  "Nonblocking Fat Tree Topology"

  def __init__(self, k=2, cpu=.1, bw=1000, delay=None,
         max_queue_size=None, **params):

    # Initialize topo
    Topo.__init__(self, **params)
    
    # Ensure k is even
    if k % 2 != 0:
      raise Exception('k must be even')
    
    switch = self.add_switch('s1')

    for host_index in range((k**3) / 4):
      host = self.add_host(get_host_name(k, host_index))
      self.add_link(host, switch, port1=0, port2=host_index)
    
# Host index is in [0, k**3/4)
def get_host_name(k, host_index):
  pod_index = host_index / (k**2 / 4)
  edge_index = (host_index % (k**2 / 4)) / (k / 2)
  link_index = host_index % (k / 2) + 2
  return '%d_%d_%d' % (pod_index, edge_index, link_index)

def get_host_index(k, pod, edge, link):
  return (pod * (k**2 / 4)) + edge *(k/2) + link - 2

# Begin traffic pettern #######################

def compute_stride(k, stride):
  matrix = []
  for src_index in range(k**3 / 4):
    matrix.append((src_index + stride) % (k**3 / 4))
  return matrix

def compute_stagger_prob(k, sameEdgeProb, samePodProb):
  if k == 2:
    return [1, 0] # The only way not to send flows to oneself.
  matrix = []
  for host_index in range((k**3)/4):
    p = host_index / (k**2 / 4)
    e = (host_index % (k**2 / 4)) / (k / 2)
    l = host_index % (k / 2) + 2 
    if random.random() < sameEdgeProb: # Put dst in same edge switch
      nl = 2 + random.randint(0, k/2 - 1)
      while nl == l:
        nl = 2 + random.randint(0, k/2 - 1)
      matrix.append(get_host_index(k,p,e,nl))
    elif random.random() < samePodProb: # Put dst in same pod but different edge
      l = 2 + random.randint(0, k/2 - 1)
      ne = random.randint(0, k/2 - 1)
      while ne == e:
        ne = random.randint(0, k/2 - 1)
      matrix.append(get_host_index(k,p,ne,l))
    else: #Put in different pod
      np = random.randint(0, k-1)
      while np == p:
        np = random.randint(0, k-1)
      l = 2 + random.randint(0, k/2 - 1)        
      e = random.randint(0, k/2 - 1)
      matrix.append(get_host_index(k,np,e,l))
  return matrix

def compute_random(k):
  matrix = []
  nHosts = (k**3)/4 - 1
  for ind in range(nHosts + 1):
    dst = random.randint(0, nHosts)
    while dst == ind:
      dst = random.randint(0, nHosts)
    matrix.append(dst)
  return matrix

def compute_randbij(k):
  matrix = range(0, (k**3)/4)
  random.shuffle(matrix)
  return matrix

# End traffic pattern ########################

def start_tcpprobe():
  os.system("rmmod tcp_probe 1>/dev/null 2>&1; modprobe tcp_probe")
  Popen("cat /proc/net/tcpprobe >/dev/null", shell=True)

def stop_tcpprobe():
  os.system("killall -9 cat; rmmod tcp_probe 1>/dev/null 2>&1")

def wait_listening(client, server, port):
  "Wait until server is listening on port"
  if not 'telnet' in client.cmd('which telnet'):
    raise Exception('Could not find telnet')
  cmd = ('sh -c "echo A | telnet -e A %s %s"' %
         (server.IP(), port))
  while 'Connected' not in client.cmd(cmd):
    output('waiting for', server,
           'to listen on port', port, '\n')
    sleep(.5)

def run_expt(net, k, flowsToCreate):
  "Run experiment"

  seconds = args.time
  
  port = 5001
  
  # Start receivers
  dstSet = set([p[1] for p in flowsToCreate])
  for dest_index in dstSet:
    dest_host_name = get_host_name(k, dest_index)
    dest = net.getNodeByName(dest_host_name)
    dest.cmd('%s -s -p %s > /dev/null &' % (IPERF_PATH, port))
  
  for src_index, dest_index in flowsToCreate:
    src = net.getNodeByName(get_host_name(k, src_index))
    dest = net.getNodeByName(get_host_name(k, dest_index))
    wait_listening(src, dest, port)
  
  print "Listeners waiting"

  # Start the bandwidth and cwnd monitors in t1he background
  monitor = Process(target=monitor_devs_ng, args=('%s/bwm.txt' % args.dir, 1.0))
  monitor.start()

  start_tcpprobe()
  
  # Start the senders
  for src_index, dest_index in flowsToCreate:
    src = net.getNodeByName(get_host_name(k, src_index))
    dest = net.getNodeByName(get_host_name(k, dest_index))
    src.cmd('%s -c %s -p %s -t %d -i 1 -yc > /dev/null &' % (IPERF_PATH, dest.IP(), port, seconds))

  print "Senders sending"

  for i in range(seconds):
    print "%d s elapsed" % i
    sleep(1)

  print "Ending experiment"
  os.system('killall -9 ' + IPERF_PATH)

  # Shut down monitors
  print "Waiting for monitor to stop"
  monitor.terminate()
  os.system('killall -9 bwm-ng')
  stop_tcpprobe()

def addMatrixToFlow(flowToCreate, matrix):
  for i in range(len(matrix)):
    flowToCreate.append((i, matrix[i]))

def check_prereqs():
  "Check for necessary programs"
  prereqs = ['telnet', 'bwm-ng', 'iperf', 'ping']
  for p in prereqs:
    if not quietRun('which ' + p):
      raise Exception((
        'Could not find %s - make sure that it is '
        'installed and in your $PATH') % p)

def main():
  "Create and run experiment"
  start = time()
 
  if 'seed' in vars(args):
    random.seed(args.seed)

  k = args.k
  host = custom(CPULimitedHost, cpu=4.0/(k**3))
  link = custom(TCLink, bw=args.bw, delay='0ms')

  if args.control:
    topo = NonblockingFatTreeTopo(k=k)
    net = Mininet(topo=topo, host=host, link=link, build=True, cleanup=True, autoPinCpus=True, autoSetMacs=True)
  else:
    topo = FatTreeTopo(k=k)
    net = Mininet(topo=topo, host=host, link=link, build=True, cleanup=True, autoPinCpus=True, autoSetMacs=True, controller=RemoteController)
  net.start()

  flowsToCreate = []
  for fcount in range(args.fph):
    if args.traffic.startswith('stride'):
      stride_amt = int(args.traffic.split(',')[1])
      matrix = compute_stride(k, stride_amt)
    elif args.traffic.startswith('stag'):
      edge_prob, pod_prob = map(float, args.traffic.split(',')[1:])
      matrix = compute_stagger_prob(k, edge_prob, pod_prob)
    elif args.traffic.startswith('random'):
      matrix = compute_random(k)
    elif args.traffic.startswith('randbij'):
      matrix = compute_randbij(k)
    else:
      raise Exception('Unrecognized traffic type')
    print "Running with matrix", matrix
    addMatrixToFlow(flowsToCreate, matrix)

  if args.controller:
    controller = Popen(args.controller, shell=True, preexec_fn=os.setsid)

  # NOTE: special signal for random number of flows
  if args.fph >= 6:
   random.shuffle(flowsToCreate)
   flowsToCreate = flowsToCreate[0:len(flowsToCreate)/2]

  start = time()
  run_expt(net, k, flowsToCreate)
  end = time()

  if args.controller:
    os.killpg(controller.pid, signal.SIGKILL)

  net.stop()
  
if __name__ == '__main__':
  check_prereqs()
  main()
