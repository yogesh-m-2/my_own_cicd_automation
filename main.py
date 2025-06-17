import threading
import uuid
import subprocess
import os
import git
import tempfile
import shutil
import json
from pathlib import Path
from flask import Flask, render_template, request, redirect, flash, jsonify, send_file

app = Flask(__name__)
app.secret_key = "super-secret-key"

PROJECTS_FILE = Path("projects.json")
BUILDS_DIR = Path("builds")
build_statuses = {}

# Create builds directory if it doesn't exist
BUILDS_DIR.mkdir(exist_ok=True)

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
        build_type = config['build_type']
        file_modifications = config.get('file_modifications', [])

        def log(line):
            nonlocal logs
            logs += line + '\n'
            build_statuses[build_id] = {"status": "running", "logs": logs}

        log(f"Cloning repository: {repo_url} (branch: {branch})")
        git.Repo.clone_from(repo_url, temp_dir, branch=branch)

        # Modify files before build, if specified
        for modification in file_modifications:
            file_path = modification.get('path')
            file_content = modification.get('content')
            if file_path and file_content:
                full_modify_path = os.path.join(temp_dir, file_path)
                try:
                    log(f"Modifying file: {file_path}")
                    with open(full_modify_path, 'w') as f:
                        f.write('\n' + file_content)
                    log(f"Successfully modified {file_path}")
                except Exception as e:
                    log(f"Failed to modify file: {e}")

        if build_type == 'maven':
            log("Running Maven build...")
            result = subprocess.run(['mvn', '-f', config['backend_pom_path'], 'clean', 'package'], 
                                 cwd=temp_dir, capture_output=True, text=True)
        elif build_type == 'npm':
            log("Installing NPM dependencies...")
            subprocess.run(['npm', 'install'], cwd=os.path.join(temp_dir, config['frontend_path']), 
                         capture_output=True, text=True)
            log("Running NPM build...")
            result = subprocess.run(['npm', 'run', 'build', '--prefix', config['frontend_path']], 
                                 cwd=temp_dir, capture_output=True, text=True)
        elif build_type == 'react_native':
            log("Running React Native build...")
            gradle_path = config['gradle_path']
            build_dir = os.path.join(temp_dir, gradle_path)
            
            # Run gradle build
            result = subprocess.run(['./gradlew', 'assembleRelease'], 
                                 cwd=build_dir, capture_output=True, text=True)
            
            if result.returncode == 0:
                # Find the APK file
                apk_dir = os.path.join(build_dir, 'app', 'build', 'outputs', 'apk', 'release')
                apk_files = [f for f in os.listdir(apk_dir) if f.endswith('.apk')]
                
                if apk_files:
                    # Create a unique filename for the APK
                    apk_filename = f"{project_name}_{build_id}.apk"
                    apk_path = BUILDS_DIR / apk_filename
                    
                    # Copy the APK to the builds directory
                    shutil.copy2(os.path.join(apk_dir, apk_files[0]), apk_path)
                    log(f"APK built and saved as {apk_filename}")
                else:
                    log("No APK file found in the build output")
            else:
                log("Gradle build failed")

        log(result.stdout + '\n' + result.stderr)
        if result.returncode != 0:
            build_statuses[build_id] = {"status": "fail", "logs": logs}
            return

        if build_type in ['maven', 'npm']:
            dockerfile_dir = os.path.join(temp_dir, config['dockerfile_path'])
            log(f"Building Docker image: {config['docker_image']} from {config['dockerfile_path']}")
            subprocess.run(['docker', 'build', '-t', config['docker_image'], '.'], 
                         cwd=dockerfile_dir, capture_output=True, text=True)

            log("Tagging Docker image...")
            tag_result = subprocess.run(['docker', 'tag', config['docker_image'], config['docker_image']], 
                                     cwd=temp_dir, capture_output=True, text=True)
            log(tag_result.stdout + '\n' + tag_result.stderr)

            log("Pushing Docker image...")
            push_result = subprocess.run(['docker', 'push', config['docker_image']], 
                                      cwd=temp_dir, capture_output=True, text=True)
            log(push_result.stdout + '\n' + push_result.stderr)

            if 'denied: requested access to the resource is denied' in push_result.stderr:
                build_statuses[build_id] = {
                    "status": "auth_required",
                    "logs": logs + "\nDocker Hub access denied. Please enter your Docker username and token to authenticate.",
                    "docker_image": config['docker_image']
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

    project_data = {
        'repo_url': data['repo_url'],
        'branch': data['branch'],
        'build_type': data['build_type'],
        'file_modifications': data.get('file_modifications', [])
    }

    # Add build type specific fields
    if data['build_type'] == 'maven':
        project_data.update({
            'backend_pom_path': data.get('backend_pom_path', ''),
            'frontend_path': data.get('frontend_path', ''),
            'docker_image': data.get('docker_image', ''),
            'dockerfile_path': data.get('dockerfile_path', '')
        })
    elif data['build_type'] == 'npm':
        project_data.update({
            'frontend_path': data.get('frontend_path', ''),
            'docker_image': data.get('docker_image', ''),
            'dockerfile_path': data.get('dockerfile_path', '')
        })
    elif data['build_type'] == 'react_native':
        project_data.update({
            'gradle_path': data.get('gradle_path', '')
        })

    projects[project_name] = project_data
    save_projects(projects)
    return jsonify({'status': 'success'})

@app.route('/project/<project_name>')
def get_project(project_name):
    projects = load_projects()
    if project_name not in projects:
        return jsonify({'status': 'error', 'message': 'Project not found'}), 404
    return jsonify(projects[project_name])

@app.route('/builds')
def list_builds():
    builds = []
    for file in BUILDS_DIR.glob('*.apk'):
        builds.append({
            'filename': file.name,
            'size': file.stat().st_size,
            'created': file.stat().st_mtime
        })
    return jsonify(builds)

@app.route('/builds/<filename>')
def download_build(filename):
    file_path = BUILDS_DIR / filename
    if not file_path.exists():
        return jsonify({'status': 'error', 'message': 'File not found'}), 404
    return send_file(file_path, as_attachment=True)

@app.route('/builds/<filename>', methods=['DELETE'])
def delete_build(filename):
    file_path = BUILDS_DIR / filename
    if not file_path.exists():
        return jsonify({'status': 'error', 'message': 'File not found'}), 404
    file_path.unlink()
    return jsonify({'status': 'success'})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=9000)