document.getElementById('create-project-form').addEventListener('submit', async function(e) {
    e.preventDefault();
    const formData = new FormData(e.target);
    const data = Object.fromEntries(formData.entries());

    const response = await fetch('/create_project', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data)
    });

    const result = await response.json();
    if (result.status === 'success') {
        alert('Project saved successfully!');
        location.reload();
    } else {
        alert('Failed to save project.');
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
