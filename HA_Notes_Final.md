# PostgreSQL High Availability Setup with Patroni, etcd, and HAProxy

**Version:** 1.0  
**Last Updated:** November 2024  
**Compatible with:** Ubuntu 22.04, PostgreSQL 14, Patroni 3.0, HAProxy 2.4

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Component Roles and Responsibilities](#component-roles-and-responsibilities)
3. [Prerequisites](#prerequisites)
4. [Part 1: Configure etcd Cluster](#part-1-configure-etcd-cluster)
5. [Part 2: Configure Patroni on PostgreSQL Nodes](#part-2-configure-patroni-on-postgresql-nodes)
6. [Part 3: Configure Second PostgreSQL Node](#part-3-configure-second-postgresql-node)
7. [Part 4: Configure HAProxy](#part-4-configure-haproxy)
8. [Part 5: Configure keepalived for HAProxy Failover](#part-5-configure-keepalived-for-haproxy-failover)
9. [Part 6: Testing and Validation](#part-6-testing-and-validation)
10. [Part 7: Maintenance Operations](#part-7-maintenance-operations)
11. [Part 8: Troubleshooting Guide](#part-8-troubleshooting-guide)
12. [Part 9: Monitoring and Alerts](#part-9-monitoring-and-alerts)
13. [Part 10: Performance Optimization](#part-10-performance-optimization)
14. [Conclusion](#conclusion)
15. [Appendix: Quick Reference Commands](#appendix-quick-reference-commands)

---

## Architecture Overview

```
┌─────────────────────────────────────┐
│         Client Applications          │
└─────────────┬───────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│         Virtual IP (VIP)             │
│         192.168.32.134               │
└─────────────┬───────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│    HAProxy Active/Standby Pair       │
│         (keepalived managed)         │
└─────────────┬───────────────────────┘
              │
              │ (Routes to Leader)
              │
┌─────────────┴───────────────────────┐
│                                     │
▼                                     ▼
┌──────────────────────────────┐    ┌──────────────────────────────┐
│      Node 1 (Primary/Leader) │    │     Node 2 (Replica/Standby) │
│         192.168.32.130       │    │        192.168.32.131        │
│                              │    │                              │
│  ┌────────────────────────┐  │    │  ┌────────────────────────┐  │
│  │   PostgreSQL 14         │  │    │  │   PostgreSQL 14         │  │
│  │   Port: 5432           │  │    │  │   Port: 5432           │  │
│  └────────────────────────┘  │    │  └────────────────────────┘  │
│  ┌────────────────────────┐  │    │  ┌────────────────────────┐  │
│  │   Patroni Agent         │  │    │  │   Patroni Agent         │  │
│  │   Port: 8008           │  │    │  │   Port: 8008           │  │
│  └────────────────────────┘  │    │  └────────────────────────┘  │
└──────────────┬───────────────┘    └──────────────┬───────────────┘
              │                                     │
              │  (Leader Election & Configuration)  │
              │                                     │
              └──────────────┬──────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────┐
│         etcd Cluster                 │
│      etcdnode: 192.168.32.140        │
│      Port: 2379                      │
│                                      │
│  (Distributed Consensus & State      │
│   Management for Patroni)           │
└─────────────────────────────────────┘
```

**HAProxy Nodes:**
- haproxynode1: 192.168.32.135 (Primary/Active)
- haproxynode2: 192.168.32.136 (Backup/Standby)

---

## Component Roles and Responsibilities

| Node | Role | Ports | Description |
|------|------|-------|-------------|
| node1 | PostgreSQL Primary | 5432, 8008 | Main database server handling writes |
| node2 | PostgreSQL Replica | 5432, 8008 | Standby server handling reads |
| etcdnode | Distributed Store | 2379, 2380 | Stores cluster state and coordinates leader election |
| haproxynode1 | Load Balancer (Active) | 5000, 7000 | Routes traffic to current leader and provides stats |
| haproxynode2 | Load Balancer (Standby) | 5000, 7000 | Standby load balancer for HA |
| VIP | Virtual IP | 192.168.32.134 | Floating IP managed by keepalived |

---

## Prerequisites

### Server Configuration

5 Ubuntu 22.04 servers with the following IP addresses:

| Node | IP Address |
|------|------------|
| node1 | 192.168.32.130 |
| node2 | 192.168.32.131 |
| etcdnode | 192.168.32.140 |
| haproxynode1 | 192.168.32.135 |
| haproxynode2 | 192.168.32.136 |

### Minimum Requirements per Node

- 2 CPU cores
- 4GB RAM
- 20GB storage

### Network Requirements

- All nodes must communicate with each other
- Ports: 5432, 8008, 2379, 2380, 5000, 7000 must be open
- VRRP Protocol (112) must be allowed between HAProxy nodes for keepalived

---

## Part 1: Configure etcd Cluster

**Node:** etcdnode (192.168.32.140)

### Step 1.1: Update System and Install Dependencies

```bash
# Update package list
sudo apt update -y

# Install basic tools
sudo apt install -y net-tools wget curl gnupg lsb-release
```

### Step 1.2: Configure Hostname

```bash
# Set hostname
sudo hostnamectl set-hostname etcdnode

# Update /etc/hosts
cat << EOF | sudo tee -a /etc/hosts
192.168.32.130 node1
192.168.32.131 node2
192.168.32.140 etcdnode
192.168.32.135 haproxynode1
192.168.32.136 haproxynode2
192.168.32.134 vip
EOF
```

### Step 1.3: Install etcd

```bash
# Install etcd package
sudo apt install -y etcd
```

### Step 1.4: Configure etcd

Edit the configuration file:

```bash
sudo nano /etc/default/etcd
```

Replace the contents with:

```bash
# etcd configuration for single node cluster
ETCD_LISTEN_PEER_URLS="http://192.168.32.140:2380"
ETCD_LISTEN_CLIENT_URLS="http://localhost:2379,http://192.168.32.140:2379"
ETCD_INITIAL_ADVERTISE_PEER_URLS="http://192.168.32.140:2380"
ETCD_INITIAL_CLUSTER="default=http://192.168.32.140:2380"
ETCD_ADVERTISE_CLIENT_URLS="http://192.168.32.140:2379"
ETCD_INITIAL_CLUSTER_TOKEN="etcd-cluster"
ETCD_INITIAL_CLUSTER_STATE="new"
```

### Step 1.5: Start and Validate etcd

```bash
# Restart etcd service
sudo systemctl restart etcd

# Enable etcd to start on boot
sudo systemctl enable etcd

# Check status
sudo systemctl status etcd

# Verify etcd is working
curl http://192.168.32.140:2379/version

# Check cluster members
curl http://192.168.32.140:2380/members
```

---

## Part 2: Configure Patroni on PostgreSQL Nodes

**Node:** node1 (192.168.32.130)

### Step 2.1: System Preparation

```bash
# Update system
sudo apt update -y

# Install basic tools
sudo apt install -y net-tools wget curl

# Set hostname
sudo hostnamectl set-hostname node1

# Update /etc/hosts
cat << EOF | sudo tee -a /etc/hosts
192.168.32.130 node1
192.168.32.131 node2
192.168.32.140 etcdnode
192.168.32.135 haproxynode1
192.168.32.136 haproxynode2
192.168.32.134 vip
EOF
```

### Step 2.2: Install PostgreSQL

```bash
# Install PostgreSQL 14 and development libraries
sudo apt install -y postgresql postgresql-server-dev-14 postgresql-client-14

# Stop the default PostgreSQL service (Patroni will manage it)
sudo systemctl stop postgresql
sudo systemctl disable postgresql

# Remove default data directory
sudo rm -rf /var/lib/postgresql/14/main
```

### Step 2.3: Link PostgreSQL Binaries

```bash
# Create symbolic links for PostgreSQL binaries
sudo ln -s /usr/lib/postgresql/14/bin/* /usr/sbin/

# Verify
ls -la /usr/sbin/ | grep postgres
```

### Step 2.4: Install Python and Patroni

```bash
# Install Python and pip
sudo apt install -y python3 python3-pip python3-venv

# Install required Python packages
sudo pip3 install --upgrade pip setuptools
sudo pip3 install patroni python-etcd psycopg2-binary
```

### Step 2.5: Create Patroni Data Directory

```bash
# Create data directory
sudo mkdir -p /data/patroni

# Set proper ownership
sudo chown postgres:postgres /data/patroni

# Set proper permissions
sudo chmod 750 /data/patroni
```

### Step 2.6: Configure Patroni

Create the Patroni configuration file:

```bash
sudo nano /etc/patroni.yml
```

Add the following configuration:

```yaml
scope: postgres
namespace: /db/
name: node1

restapi:
    listen: 192.168.32.130:8008
    connect_address: 192.168.32.130:8008

etcd:
    host: 192.168.32.140:2379

bootstrap:
  dcs:
    ttl: 30
    loop_wait: 10
    retry_timeout: 10
    maximum_lag_on_failover: 1048576
    postgresql:
      use_pg_rewind: true
      use_slots: true
      parameters:
  initdb:
  - encoding: UTF8
  - data-checksums
  pg_hba:
  - host replication replicator 127.0.0.1/32 md5
  - host replication replicator 192.168.32.130/0 md5
  - host replication replicator 192.168.32.131/0 md5
  - host all all 0.0.0.0/0 md5
  users:
    admin:
      password: admin
      options:
        - createrole
        - createdb

postgresql:
  listen: 192.168.32.130:5432
  connect_address: 192.168.32.130:5432
  data_dir: /data/patroni
  pgpass: /tmp/pgpass
  authentication:
    replication:
      username: replicator
      password: admin@123
    superuser:
      username: postgres
      password: admin@123
  parameters:
    unix_socket_directories: '.'

tags:
    nofailover: false
    noloadbalance: false
    clonefrom: false
    nosync: false
```

### Step 2.7: Create Systemd Service for Patroni

```bash
sudo nano /etc/systemd/system/patroni.service
```

Add the following content:

```ini
[Unit]
Description=PostgreSQL High Availability with Patroni
After=syslog.target network.target
After=etcd.service

[Service]
Type=simple
User=postgres
Group=postgres
ExecStart=/usr/local/bin/patroni /etc/patroni.yml
KillMode=process
TimeoutSec=30
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Step 2.8: Start Patroni Service

```bash
# Reload systemd
sudo systemctl daemon-reload

# Start Patroni
sudo systemctl start patroni

# Enable Patroni to start on boot
sudo systemctl enable patroni

# Check status
sudo systemctl status patroni
```

### Step 2.9: Verify Patroni Installation

```bash
# Check cluster status
patronictl -c /etc/patroni.yml list

# Check Patroni REST API
curl http://192.168.32.130:8008/patroni
```

---

## Part 3: Configure Second PostgreSQL Node

**Node:** node2 (192.168.32.131)

### Step 3.1: System Preparation

```bash
# Update system
sudo apt update -y

# Install basic tools
sudo apt install -y net-tools wget curl

# Set hostname
sudo hostnamectl set-hostname node2

# Update /etc/hosts
cat << EOF | sudo tee -a /etc/hosts
192.168.32.130 node1
192.168.32.131 node2
192.168.32.140 etcdnode
192.168.32.135 haproxynode1
192.168.32.136 haproxynode2
192.168.32.134 vip
EOF
```

### Step 3.2: Install PostgreSQL and Patroni

```bash
# Install PostgreSQL
sudo apt install -y postgresql postgresql-server-dev-14 postgresql-client-14

# Stop default PostgreSQL
sudo systemctl stop postgresql
sudo systemctl disable postgresql
sudo rm -rf /var/lib/postgresql/14/main

# Link PostgreSQL binaries
sudo ln -s /usr/lib/postgresql/14/bin/* /usr/sbin/

# Install Python and Patroni
sudo apt install -y python3 python3-pip
sudo pip3 install --upgrade pip setuptools
sudo pip3 install patroni python-etcd psycopg2-binary

# Create data directory
sudo mkdir -p /data/patroni
sudo chown postgres:postgres /data/patroni
sudo chmod 750 /data/patroni
```

### Step 3.3: Configure Patroni for node2

Create configuration file:

```bash
sudo nano /etc/patroni.yml
```

Add the configuration (note the differences from node1):

```yaml
scope: postgres
namespace: /db/
name: node2

restapi:
    listen: 192.168.32.131:8008
    connect_address: 192.168.32.131:8008

etcd:
    host: 192.168.32.140:2379

bootstrap:
  dcs:
    ttl: 30
    loop_wait: 10
    retry_timeout: 10
    maximum_lag_on_failover: 1048576
    postgresql:
      use_pg_rewind: true
      use_slots: true
      parameters:
  initdb:
  - encoding: UTF8
  - data-checksums
  pg_hba:
  - host replication replicator 127.0.0.1/32 md5
  - host replication replicator 192.168.32.130/0 md5
  - host replication replicator 192.168.32.131/0 md5
  - host all all 0.0.0.0/0 md5
  users:
    admin:
      password: admin
      options:
        - createrole
        - createdb

postgresql:
  listen: 192.168.32.131:5432
  connect_address: 192.168.32.131:5432
  data_dir: /data/patroni
  pgpass: /tmp/pgpass
  authentication:
    replication:
      username: replicator
      password: admin@123
    superuser:
      username: postgres
      password: admin@123
  parameters:
    unix_socket_directories: '.'

tags:
    nofailover: false
    noloadbalance: false
    clonefrom: false
    nosync: false
```

### Step 3.4: Create and Start Patroni Service

```bash
# Create systemd service file
sudo nano /etc/systemd/system/patroni.service
```

Same content as node1:

```ini
[Unit]
Description=PostgreSQL High Availability with Patroni
After=syslog.target network.target
After=etcd.service

[Service]
Type=simple
User=postgres
Group=postgres
ExecStart=/usr/local/bin/patroni /etc/patroni.yml
KillMode=process
TimeoutSec=30
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
# Start Patroni
sudo systemctl daemon-reload
sudo systemctl start patroni
sudo systemctl enable patroni
sudo systemctl status patroni
```

---

## Part 4: Configure HAProxy

**Nodes:** haproxynode1 (192.168.32.135) and haproxynode2 (192.168.32.136)

### Step 4.1: Install HAProxy

```bash
# Update system
sudo apt update -y

# Install HAProxy
sudo apt install -y haproxy net-tools curl

# Set hostname
sudo hostnamectl set-hostname haproxynode1  # or haproxynode2

# Update /etc/hosts
cat << EOF | sudo tee -a /etc/hosts
192.168.32.130 node1
192.168.32.131 node2
192.168.32.140 etcdnode
192.168.32.135 haproxynode1
192.168.32.136 haproxynode2
192.168.32.134 vip
EOF
```

### Step 4.2: Configure HAProxy

Backup the original configuration:

```bash
sudo cp /etc/haproxy/haproxy.cfg /etc/haproxy/haproxy.cfg.backup
```

Edit the HAProxy configuration:

```bash
sudo nano /etc/haproxy/haproxy.cfg
```

Replace with the following configuration:

```ini
global
    log /dev/log local0
    log /dev/log local1 notice
    maxconn 100
    user haproxy
    group haproxy
    daemon

defaults
    log global
    mode tcp
    retries 2
    timeout client 30m
    timeout connect 4s
    timeout server 30m
    timeout check 5s

# HAProxy Statistics Page
listen stats
    mode http
    bind *:7000
    stats enable
    stats uri /
    stats realm "HAProxy Statistics"
    stats auth admin:admin
    stats refresh 30s

# PostgreSQL Load Balancer
listen postgres
    bind *:5000
    mode tcp
    option httpchk OPTIONS /master
    http-check expect status 200
    default-server inter 3s fall 3 rise 2 on-marked-down shutdown-sessions
    server node1 192.168.32.130:5432 maxconn 100 check port 8008
    server node2 192.168.32.131:5432 maxconn 100 check port 8008
```

### Step 4.3: Start HAProxy

```bash
# Test configuration for syntax errors
sudo haproxy -f /etc/haproxy/haproxy.cfg -c

# Start HAProxy
sudo systemctl start haproxy

# Enable HAProxy to start on boot
sudo systemctl enable haproxy

# Check status
sudo systemctl status haproxy

# Restart if needed
sudo systemctl restart haproxy
```

### Step 4.4: Verify HAProxy

```bash
# Check if HAProxy is listening on ports
sudo netstat -tlnp | grep haproxy

# Check HAProxy statistics page (from browser or curl)
curl http://localhost:7000

# Verify PostgreSQL connectivity through HAProxy
psql -h 192.168.32.135 -p 5000 -U postgres -c "SELECT version();"
```

---

## Part 5: Configure keepalived for HAProxy Failover

**Nodes:** haproxynode1 (192.168.32.135) and haproxynode2 (192.168.32.136)

### Step 5.1: Install keepalived

```bash
# On both HAProxy nodes
sudo apt install -y keepalived
```

### Step 5.2: Configure keepalived

Create `/etc/keepalived/keepalived.conf` on both HAProxy nodes:

**On haproxynode1 (Primary/MASTER):**

```bash
sudo nano /etc/keepalived/keepalived.conf
```

```ini
! Configuration File for keepalived

global_defs {
   router_id HAProxy_VIP
}

vrrp_instance VI_1 {
    state MASTER
    interface eth0
    virtual_router_id 51
    priority 100
    advert_int 1
    authentication {
        auth_type PASS
        auth_pass your_secret_password
    }
    virtual_ipaddress {
        192.168.32.134/24 dev eth0 label eth0:vip
    }
}
```

**On haproxynode2 (Backup):**

```bash
sudo nano /etc/keepalived/keepalived.conf
```

```ini
! Configuration File for keepalived

global_defs {
   router_id HAProxy_VIP
}

vrrp_instance VI_1 {
    state BACKUP
    interface eth0
    virtual_router_id 51
    priority 90
    advert_int 1
    authentication {
        auth_type PASS
        auth_pass your_secret_password
    }
    virtual_ipaddress {
        192.168.32.134/24 dev eth0 label eth0:vip
    }
}
```

### Step 5.3: Start and Enable keepalived

```bash
# On both nodes
sudo systemctl enable keepalived
sudo systemctl start keepalived
sudo systemctl status keepalived
```

### Step 5.4: Verify VIP Assignment

```bash
# On the primary node, check if VIP is assigned
ip addr show eth0

# You should see the VIP address (192.168.32.134) on the primary HAProxy node
```

### Step 5.5: Test VIP Failover

```bash
# Stop keepalived on the primary node
sudo systemctl stop keepalived

# On the backup node, verify VIP has moved
ip addr show eth0

# The VIP should now be present on the backup node
```

---

## Part 6: Testing and Validation

### Step 6.1: Check Cluster Status

From either node1 or node2:

```bash
# View cluster status
patronictl -c /etc/patroni.yml list
```

Expected output:
```
# + Cluster: postgres (7123456789012345678) ----+----+-----------+
# | Member | Host          | Role    | State   | TL | Lag in MB |
# +--------+---------------+---------+---------+----+-----------+
# | node1  | 192.168.32.130| Leader  | running |  1 |           |
# | node2  | 192.168.32.131| Replica | running |  1 |         0 |
# +--------+---------------+---------+---------+----+-----------+
```

### Step 6.2: Test Connection via VIP

```bash
# Test connection through VIP
psql -h 192.168.32.134 -p 5000 -U postgres

# Create a test table
CREATE TABLE test_ha (id serial PRIMARY KEY, node_name text);

# Insert current node info
INSERT INTO test_ha (node_name) VALUES (inet_server_addr()::text);

# View results
SELECT * FROM test_ha;

# Exit
\q
```

### Step 6.3: Test HAProxy Failover

```bash
# Stop HAProxy on the active node
sudo systemctl stop haproxy

# Verify VIP has moved to the standby node
ip addr show eth0

# Test connection through VIP (should still work)
psql -h 192.168.32.134 -p 5000 -U postgres -c "SELECT inet_server_addr();"
```

### Step 6.4: Perform Failover Test

**Scenario 1: Graceful Leader Stop**

```bash
# On node1 (assuming it's the leader)
sudo systemctl stop patroni

# On node2, check cluster status
patronictl -c /etc/patroni.yml list

# node2 should now be the new leader

# Test connection through VIP
psql -h 192.168.32.134 -p 5000 -U postgres -c "SELECT inet_server_addr();"

# Restart node1
sudo systemctl start patroni

# Node1 should rejoin as replica
patronictl -c /etc/patroni.yml list
```

---

## Part 7: Maintenance Operations

### Backup Configuration

```bash
# Backup Patroni configuration
sudo cp /etc/patroni.yml /etc/patroni.yml.backup

# Backup HAProxy configuration
sudo cp /etc/haproxy/haproxy.cfg /etc/haproxy/haproxy.cfg.backup

# Backup keepalived configuration
sudo cp /etc/keepalived/keepalived.conf /etc/keepalived/keepalived.conf.backup

# Backup etcd configuration
sudo cp /etc/default/etcd /etc/default/etcd.backup
```

### Perform PostgreSQL Backup

```bash
# Backup from leader node
patronictl -c /etc/patroni.yml list
# Connect to leader and backup

pg_dumpall -h <leader_ip> -p 5432 -U postgres > backup.sql
```

### Switchover (Manual Leader Change)

```bash
# Perform graceful switchover from node1 to node2
patronictl -c /etc/patroni.yml switchover

# Follow prompts to select target replica
```

### Reboot Procedure

```bash
# To reboot a replica node safely:
sudo systemctl stop patroni
sudo reboot

# To reboot the leader node (perform switchover first):
patronictl -c /etc/patroni.yml switchover
# After switchover completes, reboot the old leader
```

---

## Part 8: Troubleshooting Guide

### Common Issues and Solutions

**Issue 1: Patroni fails to start**

```bash
# Check logs
sudo journalctl -u patroni -f

# Verify etcd connectivity
curl http://192.168.32.140:2379/version

# Check configuration syntax
python3 -c "import yaml; yaml.safe_load(open('/etc/patroni.yml'))"
```

**Issue 2: PostgreSQL replication not working**

```bash
# Check replication status on replica
psql -h 192.168.32.131 -U postgres -c "SELECT * FROM pg_stat_wal_receiver;"

# Check replication slots
psql -h 192.168.32.130 -U postgres -c "SELECT * FROM pg_replication_slots;"
```

**Issue 3: HAProxy not routing correctly**

```bash
# Check HAProxy logs
sudo tail -f /var/log/haproxy.log

# Verify health checks
curl http://192.168.32.130:8008/patroni
curl http://192.168.32.131:8008/patroni

# Check HAProxy status from stats page
curl http://localhost:7000/stats
```

**Issue 4: VIP not moving between HAProxy nodes**

```bash
# Check keepalived logs
sudo journalctl -u keepalived -f

# Verify VRRP protocol is allowed between nodes
# Check firewall rules

# Verify priorities are set correctly
# MASTER should have priority 100, BACKUP should have priority 90
```

**Issue 5: etcd cluster issues**

```bash
# Check etcd health
etcdctl endpoint health --endpoints=http://192.168.32.140:2379

# Check etcd logs
sudo journalctl -u etcd -f
```

---

## Part 9: Monitoring and Alerts

### Key Metrics to Monitor

| Component | Metric | Threshold | Action |
|-----------|--------|-----------|--------|
| Patroni | Leader Election | > 30 seconds | Alert |
| PostgreSQL | Replication Lag | > 100 MB | Investigate |
| HAProxy | Backend Health | Any DOWN | Immediate action |
| keepalived | VIP Status | Not assigned | Critical |
| etcd | Cluster Health | Quorum lost | Critical |
| System | Disk Usage | > 80% | Plan expansion |

### Health Check Script

Create a monitoring script on haproxynode1:

```bash
sudo nano /usr/local/bin/check_pg_ha.sh
```

```bash
#!/bin/bash

# Check VIP status
VIP_STATUS=$(ip addr show eth0 | grep "192.168.32.134" | wc -l)

if [ "$VIP_STATUS" -eq 0 ]; then
    echo "CRITICAL: VIP is not assigned to this node"
    exit 2
fi

# Check HAProxy backends
HAPROXY_STATS=$(curl -s http://localhost:7000/stats | grep postgres)

if echo "$HAPROXY_STATS" | grep -q "DOWN"; then
    echo "CRITICAL: Some PostgreSQL backends are DOWN"
    exit 2
fi

# Check Patroni cluster
PATRONI_STATUS=$(patronictl -c /etc/patroni.yml list 2>/dev/null)

if echo "$PATRONI_STATUS" | grep -q "Leader"; then
    echo "OK: Patroni cluster is healthy"
    exit 0
else
    echo "CRITICAL: Patroni cluster issues detected"
    exit 2
fi
```

```bash
sudo chmod +x /usr/local/bin/check_pg_ha.sh
```

### Set up Cron Job for Monitoring

```bash
sudo crontab -e
```

Add the following line to check every 5 minutes:

```bash
*/5 * * * * /usr/local/bin/check_pg_ha.sh >> /var/log/pg_ha_monitor.log
```

---

## Part 10: Performance Optimization

### PostgreSQL Performance Tuning

Add to postgresql section in patroni.yml:

```yaml
postgresql:
  parameters:
    # Memory Settings
    shared_buffers: '1GB'
    effective_cache_size: '3GB'
    work_mem: '32MB'
    maintenance_work_mem: '256MB'
    
    # Checkpoint Settings
    checkpoint_timeout: '15min'
    checkpoint_completion_target: 0.9
    max_wal_size: '4GB'
    min_wal_size: '1GB'
    
    # Replication Settings
    wal_keep_size: '1GB'
    max_wal_senders: 10
    wal_sender_timeout: '60s'
    
    # Query Optimization
    default_statistics_target: 100
    random_page_cost: 1.1
    effective_io_concurrency: 200
```

### HAProxy Performance Tuning

Update haproxy.cfg:

```ini
global
    maxconn 1000
    tune.ssl.default-dh-param 2048
    
defaults
    timeout connect 5s
    timeout client 60s
    timeout server 60s
    timeout queue 30s
    
listen postgres
    bind *:5000
    mode tcp
    option tcpka
    option tcplog
    balance roundrobin
    maxconn 500
```

---

## Conclusion

You have successfully configured a production-ready PostgreSQL High Availability cluster with:

- ✅ Automatic failover using Patroni
- ✅ Distributed consensus with etcd
- ✅ Load balancing with HAProxy
- ✅ High availability for HAProxy</tool_call>