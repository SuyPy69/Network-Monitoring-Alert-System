#!/usr/bin/env python3

from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.topo import Topo
from mininet.cli import CLI
from mininet.log import setLogLevel, info


class Team17Topo(Topo):

    def build(self):

        s1 = self.addSwitch(
            's1',
            protocols='OpenFlow10',
            failMode='secure'
        )

        # Four monitored hosts
        for i in range(1, 5):
            host = self.addHost(
                f'h{i}',
                ip=f'10.0.0.{i}/24'
            )
            self.addLink(host, s1)

        # Dedicated monitoring server
        h5 = self.addHost(
            'h5',
            ip='10.0.0.5/24'
        )
        self.addLink(h5, s1)


def run():

    topo = Team17Topo()

    net = Mininet(
        topo=topo,
        controller=None,
        switch=OVSSwitch,
        autoSetMacs=True
    )

    net.addController(
        'c0',
        controller=RemoteController,
        ip='127.0.0.1',
        port=6633
    )

    info('*** Starting network\n')
    net.start()

    try:
        CLI(net)

    finally:
        info('*** Stopping network\n')
        net.stop()


if __name__ == '__main__':
    setLogLevel('info')
    run()
