import json
from copy import deepcopy
from io import BytesIO
import zipfile
import pytest
from best_eleven.ingest import ingest_match, ingest_archive
from best_eleven.analytics import Scope, evidence_frames, rankings, player_profile
from best_eleven.fantasy import fantasy_projection, FantasyRules


def ingest(db,m,key='m1',**kwargs):
    return ingest_match(db,key,json.dumps(m).encode(),'fixture','synthetic-test-fixture',**kwargs)


def test_extra_accounting_and_non_striker_dismissal(db,match):
    ingest(db,match)
    d=db.execute('SELECT SUM(legal_ball),SUM(faced_ball),SUM(conceded),SUM(total_runs),SUM(boundary4),SUM(bowler_wickets) FROM deliveries').fetchone()
    assert tuple(d)==(5,6,10,15,1,1)
    a=db.execute("SELECT * FROM batting WHERE player_id='00000001'").fetchone()
    assert (a['runs'],a['balls'],a['outs'],a['fours'])==(8,6,1,1)
    non=db.execute("SELECT * FROM batting WHERE player_id='00000002'").fetchone()
    assert (non['balls'],non['outs'])==(0,1)
    retired=db.execute("SELECT * FROM batting WHERE player_id='00000003'").fetchone()
    assert retired['outs']==0
    assert db.execute('SELECT COUNT(*) FROM wickets').fetchone()[0]==3
    assert db.execute("SELECT COUNT(*) FROM fielding WHERE kind='caught and bowled'").fetchone()[0]==1


def test_repeat_and_overlapping_source_are_idempotent(db,match):
    assert ingest(db,match)=='inserted'
    assert ingest(db,match)=='unchanged'
    assert ingest_match(db,'m1',json.dumps(match).encode(),'other','test')=='unchanged'
    assert db.execute('SELECT COUNT(*) FROM deliveries').fetchone()[0]==7
    assert db.execute('SELECT COUNT(*) FROM match_sources').fetchone()[0]==2


def test_bad_revision_rolls_back_original(db,match):
    ingest(db,match)
    match['meta']['revision']=2
    match['innings'][0]['overs'][0]['deliveries'][0]['runs']['total']=400
    with pytest.raises(ValueError,match='reconcile'):ingest(db,match)
    assert db.execute('SELECT revision FROM matches').fetchone()[0]==1
    assert db.execute('SELECT SUM(total_runs) FROM deliveries').fetchone()[0]==15


def test_revision_replaces_and_older_is_ignored(db,match):
    old=deepcopy(match);ingest(db,match)
    match['meta']['revision']=2
    match['innings'][0]['overs'][0]['deliveries'][0]['actual_delivery']='0.01'
    assert ingest(db,match)=='updated'
    assert ingest(db,old)=='older_revision_skipped'
    assert db.execute('SELECT COUNT(*) FROM deliveries').fetchone()[0]==7


@pytest.mark.parametrize('version',['2.0.0','1.2.0','0.9.0'])
def test_unreviewed_schema_is_rejected(db,match,version):
    match['meta']['data_version']=version
    with pytest.raises(ValueError,match='schema'):ingest(db,match)


def test_real_and_synthetic_cannot_mix(db,match):
    match['synthetic_notice']='Fictional data'
    with pytest.raises(ValueError,match='Synthetic'):ingest(db,match)
    ingest(db,match,synthetic=True)
    assert rankings(db,Scope(format='T20'))['matches']==0
    assert rankings(db,Scope(format='T20',dataset='demo'))['matches']==1
    match.pop('synthetic_notice')
    with pytest.raises(ValueError,match='collision'):ingest(db,match)


def test_informational_missing_does_not_discard_valid_balls(db,match):
    ingest(db,match)
    bat,bowl,app=evidence_frames(db,Scope(format='T20'))
    assert len(bat)==3 and bowl.balls.sum()==5 and len(app)==7


def test_test_match_final_day_cutoff(db,match):
    match['info']['match_type']='Test';match['info']['dates']=['2020-01-01','2020-01-05'];ingest(db,match)
    assert rankings(db,Scope(format='Test',as_of='2020-01-05'))['matches']==0
    assert rankings(db,Scope(format='Test',as_of='2020-01-06'))['matches']==1
    assert rankings(db,Scope(format='T20'))['matches']==0


def test_super_over_excluded_from_career_aggregates(db,match):
    extra=deepcopy(match['innings'][0]);extra['super_over']=True
    match['innings'].append(extra);ingest(db,match)
    bat,bowl,_=evidence_frames(db,Scope(format='T20'))
    assert bat.runs.sum()==8 and bowl.conceded.sum()==10
    assert db.execute('SELECT COUNT(*) FROM deliveries').fetchone()[0]==14


def test_every_matchup_delivery_and_zero_dismissal_bowler_remain(db,match):
    last=deepcopy(match['innings'][0]['overs'][0]['deliveries'][0]);last['bowler']='B Three';last.pop('extras');last['runs']={'batter':1,'extras':0,'total':1}
    match['innings'][0]['overs'][0]['deliveries'].insert(0,last);ingest(db,match)
    r=player_profile(db,Scope(format='T20',team='A'),'00000001')
    matchups=r['batting']['matchups']
    assert sum(g['deliveries'] for g in matchups)==8
    assert any(g['dismissals_to_bowler']==0 for g in matchups)
    assert r['spatial']['recommendations']==[]


def test_did_not_bat_is_zero_fantasy_appearance_not_absent(db,match):
    ingest(db,match)
    r=fantasy_projection(db,Scope(format='T20'),FantasyRules())
    player=next(p for p in r['players'] if p['player_id']=='00000004')
    assert player['expected_points']==0 and player['appearances']==1


@pytest.mark.parametrize('filename',['../m1.json','/m1.json','x\\m1.json'])
def test_zip_paths_are_rejected(db,match,tmp_path,filename):
    path=tmp_path/'bad.zip'
    with zipfile.ZipFile(path,'w') as z:z.writestr(filename,json.dumps(match))
    with pytest.raises(ValueError,match='Unsafe'):ingest_archive(db,path,'fixture','test')
    assert db.execute('SELECT COUNT(*) FROM matches').fetchone()[0]==0


def test_partial_archive_quarantines_bad_match(db,match,tmp_path):
    path=tmp_path/'partial.zip'
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('m1.json',json.dumps(match));z.writestr('m2.json','{}')
    result=ingest_archive(db,path,'fixture','test')
    assert result['status']=='partial' and result['counts']=={'inserted':1,'failed':1}
    assert db.execute('SELECT COUNT(*) FROM ingestion_errors').fetchone()[0]==1
