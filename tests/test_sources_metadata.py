import csv
import io
import json
import zipfile
from urllib.error import HTTPError
from urllib.request import Request
from pathlib import Path
from types import SimpleNamespace
import pytest
from best_eleven import sources
from best_eleven.sources import fetch_source, import_source_archive, SameProviderRedirect
from best_eleven.ingest import ingest_match
from best_eleven.metadata import import_metadata, FIELDS
from best_eleven.analytics import metadata_at, Scope


def archive_bytes(match):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as z:z.writestr('m1.json',json.dumps(match))
    return stream.getvalue()

class Response(io.BytesIO):
    def __init__(self,data,etag='test-v1'):
        super().__init__(data)
        self.headers={'ETag':etag,'Content-Length':str(len(data))}


def test_download_then_304_uses_receipt_and_cached_archive(db,match,tmp_path,monkeypatch):
    payload=archive_bytes(match)
    monkeypatch.setattr(sources,'build_opener',lambda *a:SimpleNamespace(open=lambda *a,**k:Response(payload)))
    first=fetch_source(db,'t20s_male',tmp_path/'raw')
    assert first['status']=='ok' and first['counts']['inserted']==1
    assert (tmp_path/'raw'/f"{first['archive_sha256']}.zip").exists()
    def unchanged(request,**kwargs):
        assert request.get_header('If-none-match')=='test-v1'
        raise HTTPError(request.full_url,304,'Not Modified',{},None)
    monkeypatch.setattr(sources,'build_opener',lambda *a:SimpleNamespace(open=unchanged))
    second=fetch_source(db,'t20s_male',tmp_path/'raw')
    assert second['status']=='not_modified'
    assert db.execute('SELECT COUNT(*) FROM matches').fetchone()[0]==1


def test_changed_archive_retains_old_raw_bytes(db,match,tmp_path,monkeypatch):
    for revision in [1,2]:
        match['meta']['revision']=revision
        payload=archive_bytes(match)
        monkeypatch.setattr(sources,'build_opener',lambda *a:SimpleNamespace(open=lambda *a,**k:Response(payload)))
        result=fetch_source(db,'t20s_male',tmp_path/'raw',force=True)
    assert len(list((tmp_path/'raw').glob('*.zip')))==2
    assert result['counts']['updated']==1


def test_html_instead_of_zip_is_not_success(db,tmp_path,monkeypatch):
    monkeypatch.setattr(sources,'build_opener',lambda *a:SimpleNamespace(open=lambda *a,**k:Response(b'<html>Challenge</html>')))
    with pytest.raises(ValueError,match='non-ZIP'):fetch_source(db,'t20s_male',tmp_path/'raw')
    assert db.execute('SELECT COUNT(*) FROM matches').fetchone()[0]==0
    assert not list((tmp_path/'raw').glob('*.part'))


def test_download_size_limit_rejects_before_ingestion(db,tmp_path,monkeypatch):
    response=Response(b'')
    response.headers['Content-Length']=str(sources.MAX_DOWNLOAD_BYTES+1)
    monkeypatch.setattr(sources,'build_opener',lambda *a:SimpleNamespace(open=lambda *a,**k:response))
    with pytest.raises(ValueError,match='limit'):fetch_source(db,'t20s_male',tmp_path/'raw')


def test_redirect_cannot_reach_another_host():
    with pytest.raises(ValueError,match='allowlist'):
        SameProviderRedirect().redirect_request(Request('https://cricsheet.org/downloads/x.zip'),None,302,'',{},'http://127.0.0.1/private')


def test_user_import_retains_a_content_addressed_copy(db,match,tmp_path):
    archive=tmp_path/'local.zip';archive.write_bytes(archive_bytes(match))
    result=import_source_archive(db,archive,'fixture','https://example.invalid/fixture',tmp_path/'raw')
    retained=tmp_path/'raw'/f"{result['archive_sha256']}.zip"
    assert retained.read_bytes()==archive.read_bytes()
    assert 'origin asserted' in result['acquisition']
    again=import_source_archive(db,archive,'fixture','https://example.invalid/fixture',tmp_path/'raw')
    assert again['counts']['unchanged']==1 and len(list((tmp_path/'raw').glob('*.zip')))==1


def metadata_csv(path,rows):
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(rows)


def test_metadata_import_respects_observed_cutoff_and_unknown_counts(db,match,tmp_path):
    ingest_match(db,'m1',json.dumps(match).encode(),'fixture','test')
    row={k:'' for k in FIELDS}
    row.update(player_id='00000001',format='T20',level='international',valid_from='2019-01-01',role='opener',batting_hand='left',source_url='https://example.invalid/source',observed_at='2021-01-01')
    path=tmp_path/'metadata.csv';metadata_csv(path,[row])
    assert import_metadata(db,path)['imported']==1
    assert not metadata_at(db,Scope(format='T20',as_of='2021-01-01'))
    current=metadata_at(db,Scope(format='T20',as_of='2021-01-02'))['00000001']
    assert current['role']=='opener' and current['captain_matches'] is None
    assert not metadata_at(db,Scope(format='Test'))


def test_metadata_import_is_atomic_on_invalid_row(db,match,tmp_path):
    ingest_match(db,'m1',json.dumps(match).encode(),'fixture','test')
    row={k:'' for k in FIELDS};row.update(player_id='00000001',format='T20',level='international',valid_from='2019-01-01',source_url='https://example.invalid',observed_at='2020-01-01')
    bad={**row,'captain_matches':'-1'}
    path=tmp_path/'metadata.csv';metadata_csv(path,[row,bad])
    with pytest.raises(ValueError):import_metadata(db,path)
    assert db.execute('SELECT COUNT(*) FROM metadata').fetchone()[0]==0
