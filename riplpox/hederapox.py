"""
Hedera+POX.  As simple a data center controller as possible.
"""
from threading import Timer, Lock
import random

from pox.core import core
from pox.lib.util import dpidToStr
import pox.openflow.libopenflow_01 as of
from pox.lib.revent import EventMixin
import pox.lib.packet.ipv4 as ipv4

from ripl.mn import topos

from util import buildTopo, getRouting

# DemandEstimation. estimate_demands(flows, num_hosts)
# flows = [{'converged': False, 'demand': ?, 'src': ?, 'dest': ?, 'receiver_limited': False}]
from demand import estimate_demands

log = core.getLogger()

# Number of bytes to send for packet_ins
MISS_SEND_LEN = 2000

# Borrowed from pox/forwarding/l2_multi
class Switch (EventMixin):
  def __init__ (self):
    self.connection = None
    self.ports = None
    self.dpid = None
    self._listeners = None

  def __repr__ (self):
    return dpidToStr(self.dpid)

  def disconnect (self):
    if self.connection is not None:
      log.debug("Disconnect %s" % (self.connection,))
      self.connection.removeListeners(self._listeners)
      self.connection = None
      self._listeners = None

  def connect (self, connection):
    if self.dpid is None:
      self.dpid = connection.dpid
    assert self.dpid == connection.dpid
    if self.ports is None:
      self.ports = connection.features.ports
    self.disconnect()
    log.debug("Connect %s" % (connection,))
    self.connection = connection
    self._listeners = self.listenTo(connection)

  def send_packet_data(self, outport, data = None):
    msg = of.ofp_packet_out(in_port=of.OFPP_NONE, data = data)
    msg.actions.append(of.ofp_action_output(port = outport))
    self.connection.send(msg)

  def send_packet_bufid(self, outport, buffer_id = -1):
    msg = of.ofp_packet_out(in_port=of.OFPP_NONE)
    msg.actions.append(of.ofp_action_output(port = outport))
    msg.buffer_id = buffer_id
    self.connection.send(msg)

  def install(self, port, match, modify = False, buf = -1):
    msg = of.ofp_flow_mod()
    msg.match = match
    if modify:
      msg.command = of.OFPFC_MODIFY_STRICT
    else:
      msg.idle_timeout = 10  
      msg.hard_timeout = 120
    msg.actions.append(of.ofp_action_output(port = port))
    msg.buffer_id = buf
    self.connection.send(msg)

  def _handle_ConnectionDown (self, event):
    self.disconnect()
    pass


class RipLController(EventMixin):

  def __init__ (self, t, r, bw):
    self.switches = {}  # Switches seen: [dpid] -> Switch
    self.t = t  # Master Topo object, passed in and never modified.
    self.r = r  # Master Routing object, passed in and reused.
    self.bw = bw # Capacity of each link
    self.macTable = {}  # [mac] -> (dpid, port)

    # todo: generalize all_switches_up to a more general state machine.
    self.all_switches_up = False  # Sequences event handling.
    self.listenTo(core.openflow, priority=0)

    # For Hedera
    self.flowStatRequestVersion = 0
    self.demandEstimationLock = Lock()
    self.ethMapper = {}
    self.flowReserve = {} # flow['id'] -> reserveAmount (demand, path)
    self.paths = {} # flow['id'] -> (route, match, final_out_port)
    timer = Timer(3.0, self._beginDemandEstimation) #first few seconds wait.
    timer.start()

    # For GlobalFirstFit
    self.bwReservation = {}

  def _raw_dpids(self, arr):
    "Convert a list of name strings (from Topo object) to numbers."
    return [self.t.id_gen(name = a).dpid for a in arr]

  def _install_path(self, event, out_dpid, final_out_port, packet):
    "Install entries on route between two switches."
    in_name = self.t.id_gen(dpid = event.dpid).name_str()
    out_name = self.t.id_gen(dpid = out_dpid).name_str()
    route = self.r.get_route(in_name, out_name, packet)
    #log.info("route: %s" % route)
    match = of.ofp_match.from_packet(packet)
    for i, node in enumerate(route):
      node_dpid = self.t.id_gen(name = node).dpid
      if i < len(route) - 1:
        next_node = route[i + 1]
        out_port, next_in_port = self.t.port(node, next_node)
      else:
        out_port = final_out_port
      self.switches[node_dpid].install(out_port, match, False)
    if isinstance(packet.next, of.ipv4) and isinstance(packet.next.next, of.tcp):
        self.paths[(packet.next.srcip, packet.next.dstip,
          packet.next.next.srcport, packet.next.next.dstport)] = (route, match, final_out_port)

  def _handle_PacketIn(self, event):
    if not self.all_switches_up:
      #log.info("Saw PacketIn %s before all switches were up - ignoring." % event.parsed)
      return
    else:
      packet = event.parsed
      dpid = event.dpid
      #log.info("PacketIn: %s" % packet)
      in_port = event.port
      t = self.t

      # Learn MAC address of the sender on every packet-in.
      self.macTable[packet.src] = (dpid, in_port)
  
      #log.info("mactable: %s" % self.macTable)
  
      # Insert flow, deliver packet directly to destination.
      if packet.dst in self.macTable:
        out_dpid, out_port = self.macTable[packet.dst]
        self._install_path(event, out_dpid, out_port, packet)

        #log.info("sending to entry in mactable: %s %s" % (out_dpid, out_port))
        self.switches[out_dpid].send_packet_data(out_port, event.data)

      else:
        # Broadcast to every output port except the input on the input switch.
        # Hub behavior, baby!
        for sw in self._raw_dpids(t.layer_nodes(t.LAYER_EDGE)):
          ports = []
          sw_name = t.id_gen(dpid = sw).name_str()
          for host in t.down_nodes(sw_name):
            sw_port, host_port = t.port(sw_name, host)
            if sw != dpid or (sw == dpid and in_port != sw_port):
              ports.append(sw_port)
          # Send packet out each non-input host port
          # todo: send one packet only.
          for port in ports:
            #buffer_id = event.ofp.buffer_id
            #if sw == dpid:
            #  self.switches[sw].send_packet_bufid(port, event.ofp.buffer_id)
            #else:
            self.switches[sw].send_packet_data(port, event.data)
            #  buffer_id = -1


  def _handle_ConnectionUp (self, event):
    sw = self.switches.get(event.dpid)
    sw_str = dpidToStr(event.dpid)
    log.info("Saw switch come up: %s", sw_str)
    name_str = self.t.id_gen(dpid = event.dpid).name_str()
    if name_str not in self.t.switches():
      log.warn("Ignoring unknown switch %s" % sw_str)
      return
    if sw is None:
      log.info("Added fresh switch %s" % sw_str)
      sw = Switch()
      self.switches[event.dpid] = sw
      sw.connect(event.connection)
    else:
      log.info("Odd - already saw switch %s come up" % sw_str)
      sw.connect(event.connection)
    sw.connection.send(of.ofp_set_config(miss_send_len=MISS_SEND_LEN))

    if len(self.switches) == len(self.t.switches()):
      log.info("Woo!  All switches up")
      self.all_switches_up = True

  def _reflow(self, flow_id, new_route):
    old_route, match, final_out_port = self.paths[flow_id]
    if new_route != old_route:
      print "Rerouting", flow_id, old_route, new_route
      for i in range(len(new_route) - 1, -1, -1):
        node = new_route[i]
        node_dpid = self.t.id_gen(name = node).dpid
        if i < len(new_route) - 1:
          next_node = new_route[i + 1]
          out_port, next_in_port = self.t.port(node, next_node)
        else:
          out_port = final_out_port
        self.switches[node_dpid].install(out_port, match, modify=(i == len(new_route) - 1))
         
      self.paths[flow_id] = (new_route, match, final_out_port)

  def _beginDemandEstimation(self):
    if self.all_switches_up:
      self.demandEstimationLock.acquire()
      # Clear all
      self.flows = []
      self.flowQueryMsg = {} #set() # Store response to be received
      # Ask for outgoing flow from edge switches to hosts
      for sw_name in self.t.layer_nodes(self.t.LAYER_EDGE):
        connected_hosts = self.t.down_nodes(sw_name)
        sw_dpid = self.t.id_gen(name=sw_name).dpid
        self.flowQueryMsg[sw_dpid] = 0
        for host_name in connected_hosts:
          sw_port, host_port = self.t.port(sw_name, host_name)
          msg = of.ofp_stats_request()
          msg.type = of.OFPST_FLOW
          msg.body = of.ofp_flow_stats_request()
          msg.body.out_port = sw_port
          msg.body.match.nw_proto = ipv4.TCP_PROTOCOL
          self.switches[sw_dpid].connection.send(msg)
          # print "request (sw, src_port) = (" + str(sw_dpid) + ", " + str(sw_port) + ")"
          #self.flowQueryMsg.add((sw_dpid, sw_port))
          # NOTE: sw_port doesn't match what we get back from openflow.
          # So, the best we can do is to count it...
          self.flowQueryMsg[sw_dpid] += 1
      self.demandEstimationLock.release()
    timer = Timer(2.0, self._beginDemandEstimation)
    timer.start()

  def _buildMACToHostDict(self):
    self.ethMapper = {}
    hosts = self.t.hosts()
    for h in hosts:
      info = self.t.nodeInfo(h)
      self.ethMapper[info['mac']] = h

  def _handle_FlowStatsReceived(self, event):
    self.demandEstimationLock.acquire() 
    # NOTE: we might just want to lock at real estimate_demand() instead

    # Check for response validity
    sw_id = event.connection.dpid
    #print str(sw_id) + " : " + str(self.flowQueryMsg)
    if not sw_id in self.flowQueryMsg or self.flowQueryMsg[sw_id] <= 0:
      self.demandEstimationLock.release()  
      return # Bad response from switches we didn't ask
    self.flowQueryMsg[sw_id] -= 1
    if self.flowQueryMsg[sw_id] == 0:
      self.flowQueryMsg.pop(sw_id)
    
    for stat in event.stats:
      # Do things
      duration = stat.duration_sec * 1e9 + stat.duration_nsec
      if duration < 1:
        duration = 1
      # translate MAC to host
      s = str(stat.match.dl_src)
      t = str(stat.match.dl_dst)
      if not self.ethMapper.has_key(s) or not self.ethMapper.has_key(t):
        self._buildMACToHostDict()
      src = self.ethMapper[s]
      dst = self.ethMapper[t]
      demand = 8 * float(stat.byte_count) / duration / self.bw
      #print "receive (sw,port) = (" + str(sw_id) + ", " + str(stat.match.tp_src) + ") ", stat.byte_count, duration, ",", demand
      flowSignature = (stat.match.nw_src, stat.match.nw_dst, stat.match.tp_src, stat.match.tp_dst) 
      self.flows.append({'converged': False, 'demand': demand, 'src': src, 'dest': dst, 'receiver_limited': False, 'id': flowSignature})
    
    # If we got all reponse do demand estimation
    if len(self.flowQueryMsg) == 0:
      print 'Executing demand estimation.'
      # Clear Reservation from dead flow
      # TODO: this process hasn't happended yet. So never tested...
      newFlowList = []
      for flow in self.flows:
        newFlowList.append(flow['id'])
      flowIDToRemove = []
      for flowSignature in self.flowReserve:
        if flowSignature not in newFlowList:
          #That flow dies
          flowIDToRemove.append(flowSignature)
          prev = None
          demand, path = self.flowReserve[flowSignature]
          for node in path:
            if prev is not None:
              self.bwReservation[(prev, node)] -= demand
            prev = node
      for id in flowIDToRemove:
        del self.flowReserve[id]

      # Demand Estimation
      cmptable = {}
      for flow in self.flows:
        cmptable[(flow['src'], flow['dest'])] = {'orig_demand': flow['demand'],
          'new_demand' : None}
      m, norm_flows = estimate_demands(self.flows, self.t.hosts())
      for flow in norm_flows:
        cmptable[(flow['src'], flow['dest'])]['new_demand'] = flow['demand']
      for key in sorted(cmptable.iterkeys()):
        src, dst = key
        print src, dst, cmptable[key]['orig_demand'], cmptable[key]['new_demand'] 
      for flow in norm_flows:
        demand = flow['demand']
        if demand > 0.1: # Some threshold we use... all flows are big anyway
          #Global first fit:
          paths = self.r.get_all_route(flow['src'], flow['dest'])
          for path in paths:
            prev = None
            isFitHere = True
            for node in path:
              if prev is not None:
                k = (prev, node)
                prev = node
                if not self.bwReservation.has_key(k):
                  self.bwReservation[k] = 0
                if self.bwReservation[k] + demand > 1:
                  isFitHere = False
                  break
              prev = node
            if isFitHere:
              prev = None
              for node in path:
                if prev is not None:
                  k = (prev, node)
                  self.bwReservation[k] += demand
                prev = node
              self.flowReserve[flow['id']] = (demand, path)
              self._reflow(flow['id'], path[1:-1])
              break
    self.demandEstimationLock.release()

def launch(topo = None, routing = None, bw = None):
  """
  Args in format toponame,arg1,arg2,...
  """
  # Instantiate a topo object from the passed-in file.
  if not topo:
    raise Exception("please specify topo and args on cmd line")
  else:
    t = buildTopo(topo, topos)
    r = getRouting(routing, t)
    if bw is None:
      bw = 0.0 # Default 10 Mbps link
    else:
      bw = float(bw)
    bwGbps = bw / 1000

  core.registerNew(RipLController, t, r, bwGbps)

  log.info("RipL-POX running with topo=%s." % topo)
