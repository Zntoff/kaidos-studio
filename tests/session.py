import re


def authorize(client):
    page = client.get("/")
    token = re.search(r'name="kairos-csrf" content="([a-fA-F0-9]+)"', page.text)
    assert page.status_code == 200 and token, "Session bootstrap failed"
    client.headers["X-Kairos-CSRF"] = token[1]
    return client
