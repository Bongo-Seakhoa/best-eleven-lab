import pytest
from fastapi.testclient import TestClient
from best_eleven.app import create_app

@pytest.fixture
def client(demo_path):
    with TestClient(create_app(demo_path)) as c:
        yield c

def token(client):
    return {'X-Best-Eleven-Token':client.get('/api/status').json()['token']}

def test_static_app_and_security_headers(client):
    r=client.get('/')
    assert r.status_code==200 and 'Pick a side.' in r.text
    assert 'frame-ancestors' in r.headers['content-security-policy']
    assert client.get('/assets/app.js').status_code==200

def test_mutations_need_session_and_same_origin(client):
    assert client.post('/api/analyse',json={}).status_code==403
    headers=token(client)|{'Origin':'https://untrusted.invalid'}
    assert client.post('/api/analyse',json={},headers=headers).status_code==403

def test_disallowed_host_is_rejected(client):
    assert client.get('/',headers={'Host':'untrusted.invalid'}).status_code==400

def test_analyse_profile_and_real_empty_are_consistent(client,demo_scope):
    from dataclasses import asdict
    h=token(client)
    real=client.post('/api/analyse',headers=h,json={'scope':{'format':'Test'}})
    assert real.status_code==200 and real.json()['ranking']['players']==[]
    r=client.post('/api/analyse',headers=h,json={'scope':asdict(demo_scope)})
    assert r.status_code==200 and len(r.json()['selection']['eleven'])==11
    profile=client.post('/api/profile',headers=h,json={'scope':asdict(demo_scope),'player_id':r.json()['selection']['eleven'][0]['id']})
    assert profile.status_code==200 and profile.json()['spatial']['recommendations']==[]

def test_unknown_source_and_options_cannot_fetch_arbitrary_urls(client):
    h=token(client)
    assert client.post('/api/fetch',headers=h,json={'source':'https://internal.invalid'}).status_code==400
    assert client.post('/api/analyse',headers=h,json={'unknown':True}).status_code==400

def test_body_limit(client):
    r=client.post('/api/analyse',headers=token(client),content='x'*100001)
    assert r.status_code==413
