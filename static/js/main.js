document.getElementById('create-project-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const formData = new FormData(e.target);
    const data = {};
    const buildType = formData.get('build_type');

    // First collect all basic fields
    for (let [key, value] of formData.entries()) {
        if (!key.startsWith('file_modifications[')) {
            data[key] = value;
        }
    }

    // Then handle file modifications
    for (let [key, value] of formData.entries()) {
        if (key.startsWith('file_modifications[')) {
            const matches = key.match(/file_modifications\[(\d+)\]\[(path|content)\]/);
            if (matches) {
                const index = matches[1];
                const field = matches[2];
                if (!data.file_modifications) {
                    data.file_modifications = [];
                }
                if (!data.file_modifications[index]) {
                    data.file_modifications[index] = {};
                }
                data.file_modifications[index][field] = value;
            }
        }
    }

    // Filter out any empty modifications
    if (data.file_modifications) {
        data.file_modifications = data.file_modifications.filter(mod => mod.path && mod.content);
    }

    // Ensure all required fields for the build type are present
    if (buildType === 'maven') {
        data.backend_pom_path = data.backend_pom_path || '';
        data.frontend_path = data.frontend_path || '';
        data.docker_image = data.docker_image || '';
        data.dockerfile_path = data.dockerfile_path || '';
    } else if (buildType === 'npm') {
        data.frontend_path = data.frontend_path || '';
        data.docker_image = data.docker_image || '';
        data.dockerfile_path = data.dockerfile_path || '';
    } else if (buildType === 'react_native') {
        data.gradle_path = data.gradle_path || '';
    }

    try {
        const response = await fetch('/create_project', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(data)
        });
        const result = await response.json();
        if (result.status === 'success') {
            alert('Project saved successfully!');
            window.location.reload();
        } else {
            alert('Error saving project: ' + result.message);
        }
    } catch (error) {
        alert('Error saving project: ' + error);
    }
});

document.getElementById('build-form').addEventListener('submit', async function (e) {
    e.preventDefault();
    const statusElem = document.getElementById('status');
    const logsElem = document.getElementById('logs');
    statusElem.textContent = 'Starting...';
    logsElem.textContent = '';

    const formData = new FormData(e.target);
    const data = Object.fromEntries(formData.entries());

    const startResp = await fetch('/build', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });

    const { build_id } = await startResp.json();

    const pollInterval = setInterval(async () => {
        const res = await fetch(`/build/status/${build_id}`);
        const result = await res.json();

        logsElem.textContent = result.logs;
        statusElem.textContent = result.status.toUpperCase();
        statusElem.className = `status-${result.status}`;

        if (['success', 'fail', 'error'].includes(result.status)) {
            clearInterval(pollInterval);
        }

        if (result.status === 'auth_required') {
            clearInterval(pollInterval);
            document.getElementById('docker-login-modal').style.display = 'flex';
            document.getElementById('docker_image').value = result.docker_image;
            document.getElementById('docker_build_id').value = build_id;
        }
    }, 1000);
});

document.getElementById('docker-login-form').addEventListener('submit', async function(e) {
    e.preventDefault();
    const modal = document.getElementById('docker-login-modal');
    const logsElem = document.getElementById('logs');
    const statusElem = document.getElementById('status');

    const formData = new FormData(e.target);
    const data = Object.fromEntries(formData.entries());

    const response = await fetch('/docker_login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });

    const result = await response.json();
    if (result.status === 'ok') {
        statusElem.textContent = 'Retrying Push...';
    } else {
        statusElem.textContent = 'ERROR';
        logsElem.textContent += "\nDocker Login Failed:\n" + result.logs;
    }

    modal.style.display = 'none';
});

async function loadBranches() {
    const repoUrl = document.getElementById("repo_url").value;
    const response = await fetch("/branches", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo_url: repoUrl })
    });
    const data = await response.json();

    const branchSelect = document.getElementById("branch");
    branchSelect.innerHTML = "";

    if (data.status === "success") {
        data.branches.forEach(branch => {
            const option = document.createElement("option");
            option.value = branch;
            option.text = branch;
            branchSelect.appendChild(option);
        });
    } else {
        alert("Failed to load branches: " + data.message);
    }
}

// Add function to load project data for editing
async function loadProjectForEditing(projectName) {
    try {
        const response = await fetch(`/project/${projectName}`);
        const project = await response.json();
        
        // Fill form fields
        const form = document.getElementById('create-project-form');
        
        // First set the build type to show the correct fields
        const buildTypeSelect = form.elements['build_type'];
        buildTypeSelect.value = project.build_type;
        showBuildTypeFields();
        
        // Then fill in all the values
        for (let [key, value] of Object.entries(project)) {
            if (key === 'file_modifications') {
                loadFileModifications(value);
            } else {
                const input = form.elements[key];
                if (input) {
                    input.value = value;
                }
            }
        }
    } catch (error) {
        alert('Error loading project: ' + error);
    }
}

// Add event listener for project selection
document.getElementById('project-select').addEventListener('change', (e) => {
    if (e.target.value) {
        loadProjectForEditing(e.target.value);
    }
});

// Add event listener for form reset
document.getElementById('create-project-form').addEventListener('reset', () => {
    showBuildTypeFields();
});
