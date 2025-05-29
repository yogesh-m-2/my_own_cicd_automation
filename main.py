import threading
import uuid
import subprocess
import os
import git
import tempfile
import shutil
import json
from pathlib import Path

from flask import Flask, render_template, request, redirect, flash, jsonify

app = Flask(__name__)
app.secret_key = "super-secret-key"

PROJECTS_FILE = Path("projects.json")
build_statuses = {}

def run_build(build_id, data):
    logs = ""
    try:
        project_name = data['project_name']
        projects = load_projects()

        if project_name not in projects:
            build_statuses[build_id] = {"status": "error", "logs": f"Project '{project_name}' not found."}
            return

        config = projects[project_name]
        temp_dir = tempfile.mkdtemp()
        repo_url, branch = config['repo_url'], config['branch']
        backend_pom_path = config['backend_pom_path']
        frontend_path = config['frontend_path']
        docker_image = config['docker_image']
        build_type = config['build_type']
        dockerfile_path = config['dockerfile_path']
        modify_file_path = config.get('modify_file_path')
        modify_file_content = config.get('modify_file_content')

        def log(line):
            nonlocal logs
            logs += line + '\n'
            build_statuses[build_id] = {"status": "running", "logs": logs}

        log(f"Cloning repository: {repo_url} (branch: {branch})")
        git.Repo.clone_from(repo_url, temp_dir, branch=branch)

        # Modify file before build, if specified
        if modify_file_path and modify_file_content:
            full_modify_path = os.path.join(temp_dir, modify_file_path)
            try:
                log(f"Modifying file: {modify_file_path}")
                with open(full_modify_path, 'w') as f:
                    f.write('\n' + modify_file_content)
                log(f"Successfully modified {modify_file_path}")
            except Exception as e:
                log(f"Failed to modify file: {e}")

        if build_type == 'maven':
            log("Running Maven build...")
            result = subprocess.run(['mvn', '-f', backend_pom_path, 'clean', 'package'], cwd=temp_dir, capture_output=True, text=True)
        else:
            log("Installing NPM dependencies...")
            subprocess.run(['npm', 'install'], cwd=os.path.join(temp_dir, frontend_path), capture_output=True, text=True)
            log("Running NPM build...")
            result = subprocess.run(['npm', 'run', 'build', '--prefix', frontend_path], cwd=temp_dir, capture_output=True, text=True)

        log(result.stdout + '\n' + result.stderr)
        if result.returncode != 0:
            build_statuses[build_id] = {"status": "fail", "logs": logs}
            return

        dockerfile_dir = os.path.join(temp_dir, dockerfile_path)
        log(f"Building Docker image: {docker_image} from {dockerfile_path}")
        subprocess.run(['docker', 'build', '-t', docker_image, '.'], cwd=dockerfile_dir, capture_output=True, text=True)

        log("Tagging Docker image...")
        tag_result = subprocess.run(['docker', 'tag', docker_image, docker_image], cwd=temp_dir, capture_output=True, text=True)
        log(tag_result.stdout + '\n' + tag_result.stderr)

        log("Pushing Docker image...")
        push_result = subprocess.run(['docker', 'push', docker_image], cwd=temp_dir, capture_output=True, text=True)
        log(push_result.stdout + '\n' + push_result.stderr)

        if 'denied: requested access to the resource is denied' in push_result.stderr:
            build_statuses[build_id] = {
                "status": "auth_required",
                "logs": logs + "\nDocker Hub access denied. Please enter your Docker username and token to authenticate.",
                "docker_image": docker_image
            }
            return

        if push_result.returncode != 0:
            build_statuses[build_id] = {"status": "fail", "logs": logs}
            return

        build_statuses[build_id] = {"status": "success", "logs": logs}
    except Exception as e:
        build_statuses[build_id] = {"status": "error", "logs": logs + '\n' + str(e)}
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

def load_projects():
    if PROJECTS_FILE.exists():
        with open(PROJECTS_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_projects(projects):
    with open(PROJECTS_FILE, 'w') as f:
        json.dump(projects, f, indent=4)

@app.route('/')
def index():
    projects = load_projects()
    return render_template('index.html', projects=projects)

@app.route('/branches', methods=['POST'])
def branches():
    data = request.json
    repo_url = data['repo_url']
    try:
        tmp = tempfile.mkdtemp()
        repo = git.Repo.clone_from(repo_url, tmp, no_checkout=True)
        branches = [ref.name.replace("origin/", "") for ref in repo.remotes.origin.refs if "HEAD" not in ref.name]
        shutil.rmtree(tmp)
        return jsonify({'status': 'success', 'branches': branches})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/build', methods=['POST'])
def start_build():
    data = request.json
    build_id = str(uuid.uuid4())
    build_statuses[build_id] = {"status": "running", "logs": "Starting build...\n"}
    threading.Thread(target=run_build, args=(build_id, data), daemon=True).start()
    return jsonify({'build_id': build_id})

@app.route('/build/status/<build_id>')
def get_status(build_id):
    status = build_statuses.get(build_id, {'status': 'unknown', 'logs': 'Build ID not found.'})
    return jsonify(status)

@app.route('/docker_login', methods=['POST'])
def docker_login():
    data = request.json
    username = data['username']
    token = data['token']
    image = data['docker_image']
    build_id = data['build_id']

    try:
        login_result = subprocess.run(
            ['docker', 'login', '--username', username, '--password-stdin'],
            input=token,
            text=True,
            capture_output=True
        )
        if login_result.returncode != 0:
            return jsonify({'status': 'error', 'logs': login_result.stderr})

        push_result = subprocess.run(['docker', 'push', image], capture_output=True, text=True)
        logs = push_result.stdout + '\n' + push_result.stderr
        if push_result.returncode == 0:
            build_statuses[build_id] = {"status": "success", "logs": logs}
        else:
            build_statuses[build_id] = {"status": "fail", "logs": logs}
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'error', 'logs': str(e)})

@app.route('/create_project', methods=['POST'])
def create_project():
    data = request.json
    project_name = data['project_name']
    projects = load_projects()

    projects[project_name] = {
        'repo_url': data['repo_url'],
        'branch': data['branch'],
        'build_type': data['build_type'],
        'docker_image': data['docker_image'],
        'backend_pom_path': data['backend_pom_path'],
        'frontend_path': data['frontend_path'],
        'dockerfile_path': data['dockerfile_path'],
        'modify_file_path': data.get('modify_file_path', ''),
        'modify_file_content': data.get('modify_file_content', '')
    }

    save_projects(projects)
    return jsonify({'status': 'success'})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=9000)