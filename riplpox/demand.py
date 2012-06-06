#!/user/bin/python
import random

# NOTE: modified because hosts are weird numbers, not 0 to num_hosts

def estimate_demands(flows, hosts):
    M = {}
    for i in hosts:
        M[i] = {}
        for j in hosts:
            M[i][j] = {'demand': 0, 'converged': False, 'old_demand': 0}
    # TODO: should we include the number of flows into M
    while True:
        # Do useful things
        for src_index in hosts:
            estimate_src(M, flows, src_index)
        #print 'After src'
        #print_demands(M)
        for dest_index in hosts:
            estimate_dest(M, flows, dest_index)
        #print 'After dest'
        #print_demands(M)

        # Check for change
        shouldBreak = True
        for i in hosts:
            for j in hosts:
                if M[i][j]['old_demand'] != M[i][j]['demand']:
                    shouldBreak = False
                    M[i][j]['old_demand'] = M[i][j]['demand']
        if shouldBreak:
            break
        
    return (M, flows)

def estimate_src(M, flows, src_index):
    converged_demand = 0
    num_unconverged = 0
    for flow in flows:
        if flow['src'] != src_index:
            continue
        if flow['converged']:
            converged_demand += flow['demand']
        else:
            num_unconverged += 1
    if num_unconverged == 0:
        return
    equal_share = (1.0 - converged_demand) / num_unconverged
    for flow in flows:
        if flow['src'] != src_index:
            continue
        if not flow['converged']:
            M[flow['src']][flow['dest']]['demand'] = equal_share;
            #TODO: I think pseudo code miss this
            flow['demand'] = equal_share
            
def estimate_dest(M, flows, dest_index):
    total_demand = 0
    sender_limited_demand = 0
    num_receiver_limited = 0
    for flow in flows:
        if flow['dest'] != dest_index:
            continue
        flow['receiver_limited'] = True
        total_demand += flow['demand']
        num_receiver_limited += 1
    if total_demand <= 1.0:
        return
    equal_share = 1.0 / num_receiver_limited
    changed = True
    while changed:
        changed = False
        num_receiver_limited = 0
        for flow in flows:
            if flow['dest'] != dest_index:
                continue
            if flow['receiver_limited']:
                if flow['demand'] < equal_share:
                    sender_limited_demand += flow['demand']
                    flow['receiver_limited'] = False
                else:
                    num_receiver_limited += 1
        equal_share = (1.0 - sender_limited_demand) / num_receiver_limited
    for flow in flows:
        if flow['dest'] != dest_index:
            continue
        if flow['receiver_limited']:
            M[flow['src']][flow['dest']]['demand'] = equal_share
            M[flow['src']][flow['dest']]['converged'] = True
            #TODO: I think the pseudo code miss this...
            flow['converged'] = True
            flow['demand'] = equal_share

def add_flow(flows, src, dests):
    demand = 0.1 / len(dests)
    for dest in dests:
        flows.append({'converged': False, 'demand': demand, 'src': src, 'dest': dest, 'receiver_limited': False})

def print_demands(M):
    for row in M:
        for entry in row:
            print '%.2f%c' % (entry['demand'], '*' if entry['converged'] else ' '),
        print

if __name__ == '__main__':
    #num_hosts = 16
    hosts = range(16)
    flows = []
#    add_flow(flows, 0, [1, 2, 3])
#    add_flow(flows, 1, [0, 0, 2])
#    add_flow(flows, 2, [0, 3])
#    add_flow(flows, 3, [1, 1])

    for i in range(16):
        add_flow(flows, i, [random.randint(0,15)])

    # TODO: check for valid traffix matrix too. that is sum row,col <= 1
    M, norm_flows = estimate_demands(flows, hosts)
    #print 'Output'
    print_demands(M)
    #print norm_flows
    #print M
