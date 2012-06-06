#!/usr/bin/python

import os
import fnmatch
import sys
import re
from util.helper import *
import numpy

def get_stats(seq):
  return (pct(seq, 5), pct(seq, 50), pct(seq, 95))

  
def get_vals(results, controller, keys):
  return [get_stats(results[key][controller])[1] for key in keys]
    
  
def get_errs(results, controller, keys):
  stats = [get_stats(results[key][controller]) for key in keys]
  return [[stat[1] - stat[0] for stat in stats], [stat[2] - stat[1] for stat in stats]]

def pct(seq, p):
  return seq[min(len(seq) - 1, int(0.01 * p * len(seq)))]

def gather_stats(files, regex, duration):
  start = 10
  end = min(duration, max(30, duration - 10))
  pat_iface = re.compile(regex)
  totals = []
  for f in files:
    data = read_list(f)[:-1]
    rate = {}
    column = 2
    for row in data:
      try:
        ifname = row[1]
      except:
        break
      if ifname not in ['eth0', 'lo']:
        if not rate.has_key(ifname):
          rate[ifname] = []
        try:
          rate[ifname].append(float(row[column]) * 8.0 / (1 << 20))
        except:
          break
    total = None
    for k in sorted(rate.keys()):
      if pat_iface.match(k):
        if total is None:
          total = [0] * len(rate[k])
        total = [i + j for i,j in zip(rate[k], total)]
    end = min(end, len(total))
    totals.append(total)
  print 'read [%d:%d] seconds' % (start, end)
  all_rates = []
  for total in totals:
    all_rates += total[start:end]
  return sorted(all_rates)

def compute_results(target_k, duration, base_dir):
  expts = {}
  for subdir in os.listdir(base_dir):
    if subdir.startswith('expt') and os.path.isdir(os.path.join(base_dir, subdir)):
      expt, k, traffic, fph, seed, trial = subdir.split('-')
      key = (k, traffic, fph, seed)
      if int(k) != target_k:
        continue
      if key not in expts:
        expts[key] = []
      expts[key].append(subdir)
  results = {}
  for key, subdirs in expts.iteritems():
    k, traffic, fph, seed = key
    k = int(k)
    fph = int(fph)
    if fph >= 5:
      fph = fph / 2
    ft_regex = "[0-%d]_[0-%d]_1-eth\d*[24680]" % (k - 1, (k - 1) / 2)
    control_regex = "s1-eth.*"

    results[key] = {}
    try:
      for subpath in ['ecmp', 'st', 'random', 'hedera']:
        print key, subpath,
        results[key][subpath] = gather_stats([os.path.join(base_dir, subdir, subpath, 'bwm.txt') for subdir in subdirs], ft_regex, duration)
      for subpath in ['control']:
        print key, subpath,
        results[key][subpath] = gather_stats([os.path.join(base_dir, subdir, subpath, 'bwm.txt') for subdir in subdirs], control_regex, duration)
    except:
      print 'skipping'
      del results[key]
  return results

def plot_k(results, outfile, num_flows, configs):
  config_infos = {'hedera' : ('#00a410', 'Hedera (Global First Fit)'),
                  'ecmp' : ('#c00039', 'ECMP'),
                  'control' : ('#0f4c8f', 'Nonblocking'),
                  'st' : ('#93ffdc', 'Spanning Tree'),
                  'random' : ('#ffaa55', 'Random'),
                 }
  error_kw = {'ecolor': '#000000'}
  mult = 1
  width = 1.0 / (len(configs) + 1)
  offset = width
  plt.figure(figsize=(12, 4))
  plt.rc('font', size=6)
  print 'Plotting %s' % outfile
  for index, prefices in enumerate([['stag.*', 'stride.*'], ['random.*', 'randbij.*']]):
    ax = plt.subplot(2, 1, index + 1)
    ax.yaxis.grid(True)
    ax.set_ylim(bottom=0, top=160)
    ax.set_axisbelow(True)
    keys = list(itertools.chain.from_iterable([sorted([key for key in results.keys() if any([re.compile(prefix).match(key[1]) and key[2] in num_flows])]) for prefix in prefices]))
    handles = []
    for i, config in enumerate(configs):
      handles.append(plt.bar([mult * x + i * width + offset for x in range(len(keys))], get_vals(results, config, keys), width, color=config_infos[config][0], yerr=get_errs(results, config, keys), error_kw=error_kw))
    plt.xticks([mult * x + offset + (len(configs) * width) / 2 for x in range(len(keys))], [key[1] if len(num_flows) == 1 else key[1] + '-' + key[2] for key in keys], )
    plt.ylabel('Bisection Bandwidth (Mbps)')
    if index == 0:
      plt.subplots_adjust(hspace=0.4)
      plt.figlegend(handles, [config_infos[config][1] for config in configs], 'center', ncol=len(configs))
  plt.savefig(outfile, dpi=1000, bbox_inches='tight')

if __name__ == '__main__':
  
  plots = []
  try:
    k = int(sys.argv[1])
    duration = int(sys.argv[2])
    results_dir = sys.argv[3]
    index = 4
    while index < len(sys.argv):
      if sys.argv[index] != '--':
        raise Exception('Unexpected token')
      index += 1
      outfile = sys.argv[index]
      index += 1
      numflows = sys.argv[index].split(',')
      index += 1
      configs = []
      while index < len(sys.argv) and sys.argv[index] != '--':
        configs.append(sys.argv[index])
        index += 1
      plots.append((outfile, numflows, configs))

  except:
    print 'Usage: %s <k> <duration> <results_dir> <output_spec1> [<output_spec2> ..]' % sys.argv[0]
    print '  where each <output_spec> is of the form: -- <out.png> <numflows> <config1> [<config2> ..]'
    print '             <numflows> is a comma-separated list of integers'
    print '        each <config> is one of the following: ecmp, hedera, control, st, random'
    sys.exit(1)
  results = compute_results(k, duration, results_dir)
  for plot in plots:
    plot_k(results, plot[0], plot[1], plot[2])
