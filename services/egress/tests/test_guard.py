import asyncio

from falcon_egress import guard


def test_blocks_disallowed_port_and_private_ip() -> None:
    assert not asyncio.run(guard.check("example.com", 22)).allowed
    assert not asyncio.run(guard.check("127.0.0.1", 443)).allowed
    assert not asyncio.run(guard.check("169.254.169.254", 80)).allowed
    assert not asyncio.run(guard.check("10.0.0.5", 443)).allowed
