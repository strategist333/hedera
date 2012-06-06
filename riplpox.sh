#!/bin/sh

export PYTHONPATH=${PYTHONPATH}:/home/ubuntu/proj3/ripl:/home/ubuntu/proj3/riplpox
pox/pox.py --no-cli riplpox.riplpox --topo=ft,$1 --routing=$2
