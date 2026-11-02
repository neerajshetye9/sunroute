"""Smoke tests to verify environment and packaging setup."""


def test_imports():
    import cloud
    import edge
    import gateway
    import router
    import simulator

    assert all([edge, router, gateway, simulator, cloud])
