"""What came through the controller's own Cloudflare tunnel (B137): its
Cf-Ray from the loopback its cloudflared asks from, never any request
Cloudflare proxied, which a dashboard put behind Cloudflare is."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import nodes  # noqa: E402


class OwnTunnelEdge(unittest.TestCase):
    def test_the_controllers_own_cloudflared_is_the_tunnel(self):
        self.assertTrue(nodes.own_tunnel_edge(True, "127.0.0.1"))
        self.assertTrue(nodes.own_tunnel_edge(True, "::1"))

    def test_a_dashboard_behind_cloudflare_is_not(self):
        self.assertFalse(nodes.own_tunnel_edge(True, "172.17.0.1"))
        self.assertFalse(nodes.own_tunnel_edge(True, "192.168.1.20"))

    def test_no_ray_is_no_edge(self):
        self.assertFalse(nodes.own_tunnel_edge(False, "127.0.0.1"))


if __name__ == "__main__":
    unittest.main()
