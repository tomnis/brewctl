import time

from fastapi.testclient import TestClient

from .server import app

client = TestClient(app)

def test_brew_kill():
    response = client.post("/brew/start")
    assert response.status_code == 200
    # print(response.json())
    assert response.json()["status"] == "started"
    assert 'brew_id' in response.json()

    response = client.post("/brew/start")
    assert response.status_code == 409
    assert response.json() == {"detail": "brew already in progress"}

    response = client.post("/brew/kill")
    # print(response.json())
    assert response.status_code == 200
    assert response.json()["status"] == "killed"
    assert 'brew_id' in response.json()

    response = client.post("/brew/kill")
    print(response.json())
    assert response.status_code == 404
    assert response.json() == {"detail": "no brew in progress"}


def test_brew_stop():
    response = client.post("/brew/start")
    assert response.status_code == 200
    endpoint = f"/brew/stop?brew_id={response.json()['brew_id']}"
    response = client.post(endpoint)
    assert response.status_code == 200
    response = client.post(endpoint)
    assert response.status_code == 422
    response = client.post("/brew/stop")
    assert response.status_code == 422


def test_flow_rate():
    response = client.post("/brew/start")
    assert response.status_code == 200

    time.sleep(1)

    response = client.get("/brew/flow_rate")
    assert response.status_code == 200
    print(response.json())
    assert "flow_rate" in response.json()

    response = client.get("/brew/status")
    print(response.json())
    res = response.json()
    assert(float(res["current_flow_rate"]))
    assert(float(res["current_weight"]))
    # assert(int(res["scale_battery_pct"]))
    # assert False
    response = client.post("/brew/kill")
    assert response.status_code == 200




