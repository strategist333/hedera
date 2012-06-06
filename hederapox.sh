#!/bin/sh

export PYTHONPATH=${PYTHONPATH}:`pwd`/ripl:`pwd`/riplpox
pox/pox.py --no-cli riplpox.hederapox --topo=ft,$1 --routing=hashed --bw=$2
