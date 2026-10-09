from copy import deepcopy
from dataclasses import replace
import math
import pandas as pd
import pytest
from best_eleven.analytics import Scope, rankings, metadata_at, bootstrap_ratio, player_profile
from best_eleven.selection import Preferences, select_eleven, sensitivity, why_not
from best_eleven.evaluate import rolling_evaluate
from best_eleven.spatial import assess_spatial_evidence
from best_eleven.fantasy import fantasy_captains, FantasyRules


def test_demo_produces_valid_xi(demo_ranking):
    r=select_eleven(demo_ranking)
    assert r['status']=='optimal_under_declared_model'
    assert len(r['eleven'])==len({p['id'] for p in r['eleven']})==11
    assert sum(p['slot']=='keeper' for p in r['eleven'])==1
    assert r['bowling_options']>=4 and r['batting_options']>=6 and r['solver_gap']==0


def test_locks_and_exclusions_change_feasible_team(demo_ranking):
    first=select_eleven(demo_ranking)
    excluded=next(p['id'] for p in first['eleven'] if p['slot']=='bowler')
    second=select_eleven(demo_ranking,excluded=[excluded])
    assert excluded not in {p['id'] for p in second['eleven']}
    chosen={p['id'] for p in first['eleven']}
    candidate=next(p['id'] for p in demo_ranking['players'] if p['id'] not in chosen and p['matches']>=5)
    third=select_eleven(demo_ranking,locked=[candidate])
    assert candidate in {p['id'] for p in third['eleven']}
    with pytest.raises(ValueError,match='locked and excluded'):select_eleven(demo_ranking,locked=[candidate],excluded=[candidate])


def test_no_keeper_does_not_silently_relax(demo_ranking):
    r=deepcopy(demo_ranking)
    for p in r['players']:p['roles']=[v for v in p['roles'] if v!='keeper']
    assert select_eleven(r)['status']=='infeasible'


def test_budget_and_required_style_constraints(demo_ranking):
    assert select_eleven(demo_ranking,Preferences(budget=1))['status']=='infeasible'
    result=select_eleven(demo_ranking,Preferences(min_pace=2,min_spin=1))
    assert len(result['eleven'])==11
    assert select_eleven(demo_ranking,Preferences(min_pace=11,min_spin=11))['status']=='infeasible'


def test_unknown_leadership_is_not_zero(demo_ranking):
    r=deepcopy(demo_ranking);r['players'][0]['leadership_score']=None
    with pytest.raises(ValueError,match='Unknown is not zero'):select_eleven(r,Preferences(leadership=5))


def test_no_available_metadata_fails_closed(demo_ranking):
    r=deepcopy(demo_ranking)
    for p in r['players']:p['available']=None
    assert select_eleven(r,Preferences(require_available=True))['status']=='infeasible'


def test_contributions_reconcile(demo_ranking):
    r=select_eleven(demo_ranking,Preferences(sampling_caution=.5))
    for p in r['eleven']:
        c=p['contributions'];assert p['utility']==pytest.approx(c['performance']+c['experience']+c['leadership']-c['sampling_penalty'])
    assert r['objective_value']==pytest.approx(sum(p['utility'] for p in r['eleven']))


def test_sensitivity_is_repeatable_not_probability(demo_ranking):
    a=sensitivity(demo_ranking);b=sensitivity(demo_ranking)
    assert a==b and len(a['scenarios'])==4
    assert all(0<n<=4 for n in a['selection_count'].values())


def test_no_future_metadata_or_cross_format_appointments(demo_db,demo_scope):
    earlier=metadata_at(demo_db,replace(demo_scope,as_of='2025-01-01'))
    assert not earlier
    current=metadata_at(demo_db,demo_scope)
    assert len(current)==64 and all(v['format']=='Test' for v in current.values())


def test_team_membership_and_evidence_stay_scoped(demo_db,demo_scope):
    r=rankings(demo_db,demo_scope)
    assert len(r['players'])==16 and r['matches']==18
    assert all(p['teams']==[demo_scope.team] for p in r['players'])
    assert rankings(demo_db,replace(demo_scope,dataset='real'))['players']==[]


def test_sparse_intervals_not_false_precision():
    f=pd.DataFrame({'match_id':['a','b'],'runs':[0,10],'outs':[0,0]})
    assert bootstrap_ratio(f,'runs','outs')['low'] is None
    f.loc[2]=['c',5,0]
    r=bootstrap_ratio(f,'runs','outs')
    assert r['high'] is None and r['undefined_fraction']==1


def test_temporal_diagnostic_has_no_crossing_matches(demo_db,demo_scope):
    scope=replace(demo_scope,team='')
    result=rolling_evaluate(demo_db,scope)
    assert result['status']=='evaluated' and len(result['folds'])==3
    for fold in result['folds']:
        assert fold['train_end_exclusive']<fold['test_end_exclusive']
        assert fold['train_matches']>0 and fold['test_matches']>0
        assert 0<=fold['wicket_brier']<=1
        assert math.isfinite(fold['runs_rmse'])


def test_profiles_omit_spatial_recommendations(demo_db,demo_scope,demo_ranking):
    result=player_profile(demo_db,demo_scope,demo_ranking['players'][0]['id'],demo_ranking)
    assert result['spatial']['status']=='unavailable' and result['spatial']['recommendations']==[]
    assert 'archetypes' in result['bowling'] and 'venues' in result['batting']


def test_spatial_catch_only_and_even_complete_tracking_do_not_become_causal():
    assert assess_spatial_evidence([])['status']=='unavailable'
    assert assess_spatial_evidence([{'catch_location':'slip'}])['status']=='blocked'
    rec={'match_id':'a','innings':1,'ordinal':1,'field_before':[{}]*11,'shot_trajectory':{},'delivery_context':{},'outcome':'dot','capture_status':'observed'}
    full=assess_spatial_evidence([rec],{('a',1,1)})
    assert full['status']=='research_inputs_present' and full['recommendations']==[]
    assert assess_spatial_evidence([rec],{('a',1,1),('a',1,2)})['status']=='blocked'


def test_fantasy_captain_is_not_real_leadership():
    r=fantasy_captains([{'id':'a'},{'id':'b'},{'id':'c'}],{'a':10,'b':20,'c':5},FantasyRules())
    assert r['captain']=='b' and r['vice_captain']=='a'
    reverse=fantasy_captains([{'id':'a'},{'id':'b'}],{'a':10,'b':20},FantasyRules(captain_multiplier=1.5,vice_captain_multiplier=2))
    assert reverse['captain']=='a' and reverse['vice_captain']=='b'


@pytest.mark.parametrize('kw',[{'format':'ODI/T20'},{'dataset':'both'},{'since':'2025-01-01','as_of':'2020-01-01'},{'half_life_days':float('nan')}])
def test_bad_scope_rejected(kw):
    with pytest.raises(ValueError):Scope(**kw)
