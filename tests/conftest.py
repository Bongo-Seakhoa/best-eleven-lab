from copy import deepcopy
from pathlib import Path
import json
import pytest
from best_eleven.store import connect
from best_eleven.demo import make_demo
from best_eleven.analytics import Scope, rankings

@pytest.fixture
def db(tmp_path):
    connection = connect(tmp_path / 'test.sqlite')
    yield connection
    connection.close()

@pytest.fixture
def match():
    def ball(batter='A One', non='A Two', runs=0, extras=None, wickets=None, non_boundary=False):
        ex=extras or {}
        d={'batter':batter,'non_striker':non,'bowler':'B One','runs':{'batter':runs,'extras':sum(ex.values()),'total':runs+sum(ex.values())}}
        if ex:d['extras']=ex
        if wickets:d['wickets']=wickets
        if non_boundary:d['runs']['non_boundary']=True
        return d
    deliveries=[
        ball(runs=4,extras={'noballs':1}),
        ball(extras={'wides':1}),
        ball(extras={'byes':3}),
        ball(extras={'legbyes':2}),
        ball(runs=4,non_boundary=True),
        ball(wickets=[{'kind':'run out','player_out':'A Two','fielders':[{'name':'B Two'}]}]),
        ball(non='A Three',wickets=[{'kind':'caught and bowled','player_out':'A One'},{'kind':'retired hurt','player_out':'A Three'}])]
    names=['A One','A Two','A Three','A Four','B One','B Two','B Three']
    return {'meta':{'data_version':'1.1.0','revision':1,'created':'2020-01-02'},
        'info':{'balls_per_over':6,'dates':['2020-01-01'],'gender':'male','match_type':'T20','team_type':'international','season':2020,
                'teams':['A','B'],'players':{'A':names[:4],'B':names[4:]},'registry':{'people':{n:f'{i+1:08x}' for i,n in enumerate(names)}},'venue':'Fictional ground',
                'missing':['umpires']},
        'innings':[{'team':'A','overs':[{'over':0,'deliveries':deliveries}]}]}

@pytest.fixture(scope='session')
def demo_path(tmp_path_factory):
    path=tmp_path_factory.mktemp('demo')/'demo.sqlite'
    db=connect(path);make_demo(db);db.close()
    return path

@pytest.fixture
def demo_db(demo_path):
    db=connect(demo_path)
    yield db
    db.close()

@pytest.fixture
def demo_scope():
    return Scope(format='Test',team='Cedar XI (demo)',dataset='demo',as_of='2026-10-09')

@pytest.fixture
def demo_ranking(demo_db,demo_scope):
    return rankings(demo_db,demo_scope)
