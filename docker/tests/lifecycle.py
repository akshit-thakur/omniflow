"""Installation checks for a disposable stack. Replaces its tasks via restore."""
import argparse
import json
import os
from pathlib import Path
from uuid import uuid4
from .smoke import SmokeClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--disposable', action='store_true', required=True)
    parser.add_argument('--existing', action='store_true')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    client = SmokeClient(os.getenv('BASE_URL', 'http://frontend'))
    password = os.environ['LIFECYCLE_PASSWORD']
    status = client.request('/api/auth/status')
    if args.existing:
        assert not status['setup_required'], 'Credential was lost'
        client.login(password)
        assert any(row['title'] == 'Lifecycle retained task' for row in client.request('/api/tasks/')), 'Data was lost'
        print('Existing password and retained task verified')
        return
    if args.resume:
        client.login(password)
        for row in client.request('/api/tasks/'):
            if row['title'] == 'Lifecycle removed by restore':
                client.request(f"/api/tasks/{row['id']}", method='DELETE')
    else:
        assert status['setup_required'], 'Expected an empty installation'
        result = client.request('/api/auth/setup', method='POST', body={'password': password})
        client.cookies = {'__bearer__': result['access_token'], '__csrf__': result['csrf_token']}
    client.request('/api/auth/setup', method='POST', body={'password': 'cannot-replace-password'}, expected=(409,))
    assert not client.request('/api/auth/status')['setup_required']
    client.request('/api/tasks/', method='POST', body={'title': 'Lifecycle retained task'}, expected=(201,))
    snapshot = client.request('/api/backups/export/tasks')
    client.request('/api/tasks/', method='POST', body={'title': 'Lifecycle removed by restore'}, expected=(201,))
    client.request('/api/backups/restore/preview', method='POST', body={'snapshot': snapshot})
    client.request('/api/backups/restore', method='POST', body={'snapshot': snapshot})
    tasks = client.request('/api/tasks/')
    assert any(row['title'] == 'Lifecycle retained task' for row in tasks)
    assert not any(row['title'] == 'Lifecycle removed by restore' for row in tasks)
    secret_path = os.getenv('LIFECYCLE_SECRET_FILE')
    if secret_path:
        from urllib.request import Request, urlopen
        request_id = str(uuid4())
        payload = {'request_id': request_id, 'actions': [{'action': 'task.create', 'arguments': {'title': 'Lifecycle approved AI task'}}]}
        request = Request('http://api:8000/api/internal/ai/proposals', data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json', 'X-Omniflow-Secret': Path(secret_path).read_text().strip()})
        with urlopen(request) as response:
            proposal = json.load(response)
        approval = Request(f'{client.base_url}/api/ai/proposals/{request_id}/approve', data=b'{}', headers={
            'Content-Type': 'application/json', 'Origin': client.base_url,
            'Authorization': f"Bearer {client.cookies['__bearer__']}",
            'X-CSRF-Token': client.cookies['__csrf__'],
            'X-Omniflow-Review-Digest': proposal['review_digest'],
        })
        with urlopen(approval) as response:
            assert json.load(response)['status'] == 'committed'
    activity = client.request('/api/activity')
    sources = {row['source'] for row in activity}
    assert {'manual', 'restore'} <= sources, sources
    assert any(row['action'] == 'restore' and row['entity_table'] == 'backups' for row in activity)
    if secret_path:
        assert 'ai' in sources, sources
        matching = [row for row in activity if row['label'] == 'Lifecycle approved AI task']
        assert len(matching) == 1, matching
    first = client.request('/api/activity?limit=1')
    from urllib.parse import urlencode
    second = client.request('/api/activity?' + urlencode({'limit': 1, 'before': first[0]['created_at'], 'before_id': first[0]['id']}))
    assert second and first[0]['id'] != second[0]['id']
    print('First-run setup, duplicate rejection, manual writes, backup preview/restore, activity sources and pagination passed')


if __name__ == '__main__':
    main()
