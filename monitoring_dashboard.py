#!/usr/bin/env python3
"""
PostgreSQL HA Monitoring Dashboard
Provides a web interface to monitor Patroni cluster, HAProxy, and VIP status
"""

import json
import time
from datetime import datetime
from flask import Flask, render_template_string, jsonify, request
import requests
import psycopg2
import os

app = Flask(__name__)

# Configuration - update these for your environment
CONFIG = {
    "etcd_host": "192.168.32.140",
    "etcd_port": 2379,
    "patroni_nodes": [
        {"host": "192.168.32.130", "port": 8008, "name": "node1"},
        {"host": "192.168.32.131", "port": 8008, "name": "node2"},
    ],
    "haproxy_nodes": [
        {"host": "192.168.32.135", "port": 7000, "name": "haproxynode1"},
        {"host": "192.168.32.136", "port": 7000, "name": "haproxynode2"},
    ],
    "vip": "192.168.32.134",
    "vip_port": 5000,
    "refresh_interval": 10,  # seconds
}

# HTML template for the dashboard
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>PostgreSQL HA Cluster Dashboard</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        .status-indicator { display: inline-block; width: 12px; height: 12px; border-radius: 50%; margin-right: 5px; }
        .status-healthy { background-color: #28a745; }
        .status-warning { background-color: #ffc107; }
        .status-danger { background-color: #dc3545; }
        .status-unknown { background-color: #6c757d; }
        .metric-card { margin-bottom: 1rem; }
        .last-updated { font-size: 0.9em; color: #6c757d; }
        .auto-refresh { color: #0d6efd; cursor: pointer; }
    </style>
</head>
<body>
    <div class="container-fluid py-4">
        <div class="row mb-4">
            <div class="col-12">
                <h1>PostgreSQL HA Cluster Dashboard</h1>
                <p class="last-updated" id="lastUpdated">Last updated: --</p>
                <button class="btn btn-outline-primary auto-refresh" id="toggleAutoRefresh">Disable Auto-refresh</button>
            </div>
        </div>
        
        <div class="row">
            <div class="col-md-4">
                <div class="card metric-card">
                    <div class="card-body">
                        <h5 class="card-title">Cluster Status</h5>
                        <div id="clusterStatus">Loading...</div>
                    </div>
                </div>
            </div>
            
            <div class="col-md-4">
                <div class="card metric-card">
                    <div class="card-body">
                        <h5 class="card-title">VIP Status</h5>
                        <div id="vipStatus">Loading...</div>
                    </div>
                </div>
            </div>
            
            <div class="col-md-4">
                <div class="card metric-card">
                    <div class="card-body">
                        <h5 class="card-title">HAProxy Status</h5>
                        <div id="haproxyStatus">Loading...</div>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="row">
            <div class="col-12">
                <div class="card metric-card">
                    <div class="card-body">
                        <h5 class="card-title">Patroni Nodes</h5>
                        <div id="patroniNodes" class="row g-2"></div>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="row">
            <div class="col-12">
                <div class="card metric-card">
                    <div class="card-body">
                        <h5 class="card-title">HAProxy Nodes</h5>
                        <div id="haproxyNodes" class="row g-2"></div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        let autoRefreshEnabled = true;
        const refreshInterval = {{ refresh_interval }} * 1000;
        
        function updateLastUpdated() {
            document.getElementById('lastUpdated').textContent = 
                'Last updated: ' + new Date().toLocaleString();
        }
        
        function setStatusIndicator(elementId, status, text) {
            const element = document.getElementById(elementId);
            element.innerHTML = `
                <span class="status-indicator status-${status}"></span>
                ${text}
            `;
        }
        
        function fetchData() {
            fetch('/api/status')
                .then(response => response.json())
                .then(data => {
                    updateLastUpdated();
                    
                    // Update cluster status
                    const clusterStatus = data.cluster || {};
                    setStatusIndicator('clusterStatusIndicator', 
                        clusterStatus.overall_health || 'unknown',
                        clusterStatus.message || 'Checking...');
                    
                    // Update VIP status
                    const vipStatus = data.vip || {};
                    setStatusIndicator('vipStatusIndicator',
                        vipStatus.assigned ? 'healthy' : 'danger',
                        vipStatus.assigned ? `Assigned to ${vipStatus.current_holder}` : 'Not assigned');
                    
                    // Update HAProxy status
                    const haproxyStatus = data.haproxy || {};
                    setStatusIndicator('haproxyStatusIndicator',
                        haproxyStatus.healthy ? 'healthy' : 'danger',
                        haproxyStatus.healthy ? 'All nodes healthy' : 'Some nodes down');
                    
                    // Update Patroni nodes
                    const patroniNodesContainer = document.getElementById('patroniNodes');
                    patroniNodesContainer.innerHTML = '';
                    (data.patroni_nodes || []).forEach(node => {
                        const col = document.createElement('div');
                        col.className = 'col-md-6';
                        col.innerHTML = `
                            <div class="card h-100">
                                <div class="card-body">
                                    <h6 class="card-title">${node.name}</h6>
                                    <p><strong>Role:</strong> ${node.role || 'unknown'}</p>
                                    <p><strong>State:</strong> ${node.state || 'unknown'}</p>
                                    <p><strong>TL:</strong> ${node.timeline || 'N/A'}</p>
                                    <p><strong>Lag:</strong> ${node.lag || 'N/A'} MB</p>
                                    <div class="mt-2">
                                        <span class="status-indicator status-${node.status || 'unknown'}"></span>
                                        <span>${node.status || 'unknown'}</span>
                                    </div>
                                </div>
                            </div>
                        `;
                        patroniNodesContainer.appendChild(col);
                    });
                    
                    // Update HAProxy nodes
                    const haproxyNodesContainer = document.getElementById('haproxyNodes');
                    haproxyNodesContainer.innerHTML = '';
                    (data.haproxy_nodes || []).forEach(node => {
                        const col = document.createElement('div');
                        col.className = 'col-md-6';
                        col.innerHTML = `
                            <div class="card h-100">
                                <div class="card-body">
                                    <h6 class="card-title">${node.name}</h6>
                                    <p><strong>Status:</strong> ${node.status || 'unknown'}</p>
                                    <p><strong>Backend:</strong> ${node.backend || 'N/A'}</p>
                                    ${node.stats ? `<p><strong>Sessions:</strong> ${node.stats.sessions || 0}</p>` : ''}
                                    <div class="mt-2">
                                        <span class="status-indicator status-${node.status === 'UP' ? 'healthy' : node.status === 'DOWN' ? 'danger' : 'warning'}"></span>
                                        <span>${node.status || 'unknown'}</span>
                                    </div>
                                </div>
                            </div>
                        `;
                        haproxyNodesContainer.appendChild(col);
                    });
                })
                .catch(error => {
                    console.error('Error fetching data:', error);
                    document.getElementById('lastUpdated').textContent = 
                        'Last updated: Error - ' + new Date().toLocaleString();
                });
        }
        
        function toggleAutoRefresh() {
            autoRefreshEnabled = !autoRefreshEnabled;
            const btn = document.getElementById('toggleAutoRefresh');
            if (autoRefreshEnabled) {
                btn.textContent = 'Disable Auto-refresh';
                btn.className = 'btn btn-outline-primary auto-refresh';
                startAutoRefresh();
            } else {
                btn.textContent = 'Enable Auto-refresh';
                btn.className = 'btn btn-outline-success auto-refresh';
                stopAutoRefresh();
            }
        }
        
        let refreshIntervalId;
        function startAutoRefresh() {
            refreshIntervalId = setInterval(fetchData, refreshInterval);
        }
        
        function stopAutoRefresh() {
            if (refreshIntervalId) {
                clearInterval(refreshIntervalId);
                refreshIntervalId = null;
            }
        }
        
        // Initialize
        document.addEventListener('DOMContentLoaded', function() {
            fetchData();
            startAutoRefresh();
            
            document.getElementById('toggleAutoRefresh').addEventListener('click', toggleAutoRefresh);
        });
    </script>
</body>
</html>
"""


def get_etcd_status():
    """Get etcd cluster status"""
    try:
        response = requests.get(
            f"http://{CONFIG['etcd_host']}:{CONFIG['etcd_port']}/version", timeout=5
        )
        if response.status_code == 200:
            return {
                "healthy": True,
                "version": response.json().get("etcdserver", "unknown"),
            }
        else:
            return {"healthy": False, "error": f"HTTP {response.status_code}"}
    except Exception as e:
        return {"healthy": False, "error": str(e)}


def get_patroni_status(node):
    """Get status of a Patroni node"""
    try:
        response = requests.get(
            f"http://{node['host']}:{node['port']}/patroni", timeout=5
        )
        if response.status_code == 200:
            data = response.json()
            return {
                "name": node["name"],
                "host": node["host"],
                "role": data.get("role", "unknown"),
                "state": data.get("state", "unknown"),
                "timeline": data.get("timeline", "N/A"),
                "lag": data.get("lag", "N/A"),
                "status": "healthy" if data.get("state") == "running" else "warning",
            }
        else:
            return {
                "name": node["name"],
                "host": node["host"],
                "status": "error",
                "error": f"HTTP {response.status_code}",
            }
    except Exception as e:
        return {
            "name": node["name"],
            "host": node["host"],
            "status": "error",
            "error": str(e),
        }


def get_haproxy_status(node):
    """Get status of an HAProxy node"""
    try:
        response = requests.get(
            f"http://{node['host']}:{node['port']}/stats;csv", timeout=5
        )
        if response.status_code == 200:
            # Parse CSV stats (simplified)
            lines = response.text.strip().split("\\n")
            if len(lines) > 1:
                headers = lines[0].split(",")
                # Find the backend line (usually contains 'BACKEND' or is the first data line)
                backend_line = None
                for line in lines[1:]:
                    if "BACKEND" in line or "postgres" in line.lower():
                        backend_line = line
                        break
                if not backend_line and len(lines) > 1:
                    backend_line = lines[1]  # fallback to first data line

                if backend_line:
                    values = backend_line.split(",")
                    status_idx = headers.index("status") if "status" in headers else 2
                    status = (
                        values[status_idx] if status_idx < len(values) else "unknown"
                    )

                    return {
                        "name": node["name"],
                        "host": node["host"],
                        "status": status,
                        "backend": "postgres",
                        "healthy": status == "OPEN" or status == "UP",
                    }

            return {
                "name": node["name"],
                "host": node["host"],
                "status": "unknown",
                "healthy": False,
            }
        else:
            return {
                "name": node["name"],
                "host": node["host"],
                "status": "error",
                "healthy": False,
                "error": f"HTTP {response.status_code}",
            }
    except Exception as e:
        return {
            "name": node["name"],
            "host": node["host"],
            "status": "error",
            "healthy": False,
            "error": str(e),
        }


def get_vip_status():
    """Check if VIP is assigned (simplified check)"""
    try:
        # Try to connect to VIP to see if it's responding
        response = requests.get(
            f"http://{CONFIG['vip']}:{CONFIG['vip_port']}", timeout=3
        )
        # If we get any response, VIP is likely assigned
        # In a real implementation, you'd check the actual interface
        return {
            "assigned": response.status_code
            < 500,  # Any response less than 500 means something's there
            "current_holder": CONFIG["vip"],  # Simplified
            "response_time": response.elapsed.total_seconds(),
        }
    except requests.exceptions.ConnectionError:
        return {
            "assigned": False,
            "current_holder": None,
            "error": "Connection refused",
        }
    except Exception as e:
        return {"assigned": False, "current_holder": None, "error": str(e)}


@app.route("/")
def dashboard():
    return render_template_string(
        HTML_TEMPLATE, refresh_interval=CONFIG["refresh_interval"]
    )


@app.route("/api/status")
def api_status():
    # Get status from all components
    etcd_status = get_etcd_status()

    patroni_nodes = []
    patroni_healthy = True
    for node in CONFIG["patroni_nodes"]:
        status = get_patroni_status(node)
        patroni_nodes.append(status)
        if status.get("status") != "healthy":
            patroni_healthy = False

    haproxy_nodes = []
    haproxy_healthy = True
    for node in CONFIG["haproxy_nodes"]:
        status = get_haproxy_status(node)
        haproxy_nodes.append(status)
        if not status.get("healthy", False):
            haproxy_healthy = False

    vip_status = get_vip_status()

    # Determine overall cluster health
    overall_healthy = (
        etcd_status.get("healthy", False)
        and patroni_healthy
        and haproxy_healthy
        and vip_status.get("assigned", False)
    )

    return jsonify(
        {
            "cluster": {
                "healthy": overall_healthy,
                "overall_health": "healthy" if overall_healthy else "unhealthy",
                "message": (
                    "All systems operational"
                    if overall_healthy
                    else "Some components degraded"
                ),
                "etcd": etcd_status,
            },
            "patroni_nodes": patroni_nodes,
            "haproxy_nodes": haproxy_nodes,
            "vip": vip_status,
            "haproxy": {
                "healthy": haproxy_healthy,
                "nodes": len([n for n in haproxy_nodes if n.get("healthy", False)]),
            },
            "timestamp": datetime.now().isoformat(),
        }
    )


if __name__ == "__main__":
    print("Starting PostgreSQL HA Monitoring Dashboard...")
    print(f"Dashboard will be available at: http://localhost:5000")
    print("Make sure to update the CONFIG section with your actual node IPs")
    app.run(host="0.0.0.0", port=5000, debug=False)
