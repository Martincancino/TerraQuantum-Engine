import json
import urllib.request
import time
import mimetypes
import uuid

def post_multipart(url, data, files):
    boundary = uuid.uuid4().hex
    headers = {'Content-Type': f'multipart/form-data; boundary={boundary}'}
    body = bytearray()

    for key, value in data.items():
        body.extend(f'--{boundary}\r\n'.encode('utf-8'))
        body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode('utf-8'))
        body.extend(f'{value}\r\n'.encode('utf-8'))

    for key, file_info in files.items():
        filename = file_info[0]
        content = file_info[1]
        body.extend(f'--{boundary}\r\n'.encode('utf-8'))
        body.extend(f'Content-Disposition: form-data; name="{key}"; filename="{filename}"\r\n'.encode('utf-8'))
        body.extend(b'Content-Type: text/csv\r\n\r\n')
        body.extend(content)
        body.extend(b'\r\n')

    body.extend(f'--{boundary}--\r\n'.encode('utf-8'))

    req = urllib.request.Request(url, data=body, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, response.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8')

project_id = f"r23_qa_delete_me_{int(time.time())}"
run_id = f"run_r23_qa_{int(time.time())}"

data = {
    'project_id': project_id,
    'run_id': run_id,
    'lat': '-22.28',
    'lon': '-68.89',
    'utm_zone': '19S',
    'strict': 'false',
    'allow_g_raw': 'true',
    'depth': '1000',
    'nir': '0',
    'fe': '0',
    'region': 'Antofagasta',
    'nx': '10',
    'ny': '10',
    'nz': '10',
    'block_size': '1000',
    'cutoff_radius': '50000',
    'lambda_mag': '0.1',
    'alpha_spatial': '0.5'
}

with open('test_r23_qa.csv', 'rb') as f:
    files = {'file': ('test_r23_qa.csv', f.read())}

status, resp = post_multipart("http://127.0.0.1:8010/gravity-import/invert", data, files)
print(f"PROJECT_ID={project_id}")
print(f"STATUS={status}")
print("RESPONSE=")
print(resp)
