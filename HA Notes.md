Architecture Overview
This document provides a comprehensive guide to setting up a production-ready PostgreSQL High Availability (HA) cluster using Patroni, etcd, and HAProxy.

Architecture Diagram
                                    ┌─────────────────────────────────────┐
                                    │         Client Applications          │
                                    └─────────────┬───────────────────────┘
                                                  │
                                                  ▼
                                    ┌─────────────────────────────────────┐
                                    │    HAProxy Load Balancer (Port 5000) │
                                    │         haproxynode: 192.168.32.135  │
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
Component Roles and Responsibilities
node1	PostgreSQL Primary	5432, 8008	Main database server handling writes
node2	PostgreSQL Replica	5432, 8008	Standby server handling reads
etcdnode	Distributed Store	2379, 2380	Stores cluster state and coordinates leader election
haproxynode	Load Balancer	5000, 7000	Routes traffic to current leader and provides stats
Prerequisites
4 Ubuntu 22.04 servers with the following IP addresses:

node1: 192.168.32.130
node2: 192.168.32.131
etcdnode: 192.168.32.140
haproxynode: 192.168.32.135
Minimum Requirements per node:

2 CPU cores
4GB RAM
20GB storage
Network Requirements:

All nodes must communicate with each other
Ports: 5432, 8008, 2379, 2380, 5000, 7000 must be open
Part 1: Configure etcd Cluster
Node: etcdnode (192.168.32.140)

Step 1.1: Update System and Install Dependencies
# Update package list
sudo apt update -y

# Install basic tools
sudo apt install -y net-tools wget curl gnupg lsb-release
Step 1.2: Configure Hostname
# Set hostname
sudo hostnamectl set-hostname etcdnode

# Update /etc/hosts
cat << EOF | sudo tee -a /etc/hosts
192.168.32.130 node1
192.168.32.131 node2
192.168.32.140 etcdnode
192.168.32.135 haproxynode
EOF
Step 1.3: Install etcd
# Install etcd package
sudo apt install -y etcd
Step 1.4: Configure etcd
Edit the configuration file:

sudo nano /etc/default/etcd
Replace the contents with:

# etcd configuration for single node cluster
ETCD_LISTEN_PEER_URLS="http://192.168.32.140:2380"
ETCD_LISTEN_CLIENT_URLS="http://localhost:2379,http://192.168.32.140:2379"
ETCD_INITIAL_ADVERTISE_PEER_URLS="http://192.168.32.140:2380"
ETCD_INITIAL_CLUSTER="default=http://192.168.32.140:2380"
ETCD_ADVERTISE_CLIENT_URLS="http://192.168.32.140:2379"
ETCD_INITIAL_CLUSTER_TOKEN="etcd-cluster"
ETCD_INITIAL_CLUSTER_STATE="new"
Step 1.5: Start and Validate etcd
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
Expected output: JSON response showing the etcd member information.

Part 2: Configure Patroni on PostgreSQL Nodes
Node: node1 (192.168.32.130)
Step 2.1: System Preparation
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
192.168.32.135 haproxynode
EOF
Step 2.2: Install PostgreSQL
# Install PostgreSQL 14 and development libraries
sudo apt install -y postgresql postgresql-server-dev-14 postgresql-client-14

# Stop the default PostgreSQL service (Patroni will manage it)
sudo systemctl stop postgresql
sudo systemctl disable postgresql

# Remove default data directory
sudo rm -rf /var/lib/postgresql/14/main
Step 2.3: Link PostgreSQL Binaries
# Create symbolic links for PostgreSQL binaries
sudo ln -s /usr/lib/postgresql/14/bin/* /usr/sbin/

# Verify
ls -la /usr/sbin/ | grep postgres
Step 2.4: Install Python and Patroni
# Install Python and pip
sudo apt install -y python3 python3-pip python3-venv

# Install required Python packages
sudo pip3 install --upgrade pip setuptools
sudo pip3 install patroni python-etcd psycopg2-binary
Step 2.5: Create Patroni Data Directory
# Create data directory
sudo mkdir -p /data/patroni

# Set proper ownership
sudo chown postgres:postgres /data/patroni

# Set proper permissions
sudo chmod 750 /data/patroni
Step 2.6: Configure Patroni
Create the Patroni configuration file:

sudo nano /etc/patroni.yml
Add the following configuration:

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
Step 2.7: Create Systemd Service for Patroni
sudo nano /etc/systemd/system/patroni.service
Add the following content:

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
Step 2.8: Start Patroni Service
# Reload systemd
sudo systemctl daemon-reload

# Start Patroni
sudo systemctl start patroni

# Enable Patroni to start on boot
sudo systemctl enable patroni

# Check status
sudo systemctl status patroni
Step 2.9: Verify Patroni Installation
# Check cluster status
patronictl -c /etc/patroni.yml list

# Check Patroni REST API
curl http://192.168.32.130:8008/patroni
Part 3: Configure Second PostgreSQL Node
Node: node2 (192.168.32.131)
Step 3.1: System Preparation
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
192.168.32.135 haproxynode
EOF
Step 3.2: Install PostgreSQL and Patroni
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
Step 3.3: Configure Patroni for node2
Create configuration file:

sudo nano /etc/patroni.yml
Add the configuration (note the differences from node1):

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
Step 3.4: Create and Start Patroni Service
# Create systemd service file
sudo nano /etc/systemd/system/patroni.service
Same content as node1:

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
# Start Patroni
sudo systemctl daemon-reload
sudo systemctl start patroni
sudo systemctl enable patroni
sudo systemctl status patroni
Part 4: Configure HAProxy
Node: haproxynode (192.168.32.135)
Step 4.1: Install HAProxy
# Update system
sudo apt update -y

# Install HAProxy
sudo apt install -y haproxy net-tools curl

# Set hostname
sudo hostnamectl set-hostname haproxynode

# Update /etc/hosts
cat << EOF | sudo tee -a /etc/hosts
192.168.32.130 node1
192.168.32.131 node2
192.168.32.140 etcdnode
192.168.32.135 haproxynode
EOF
Step 4.2: Configure HAProxy
Backup the original configuration:

sudo cp /etc/haproxy/haproxy.cfg /etc/haproxy/haproxy.cfg.backup
Edit the HAProxy configuration:

sudo nano /etc/haproxy/haproxy.cfg
Replace with the following configuration:

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
Step 4.3: Start HAProxy
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
Step 4.4: Verify HAProxy
# Check if HAProxy is listening on ports
sudo netstat -tlnp | grep haproxy

# Check HAProxy statistics page (from browser or curl)
curl http://localhost:7000

# Verify PostgreSQL connectivity through HAProxy
psql -h 192.168.32.135 -p 5000 -U postgres -c "SELECT version();"
Part 5: Testing and Validation
Step 5.1: Check Cluster Status
From either node1 or node2:

# View cluster status
patronictl -c /etc/patroni.yml list

# Expected output:
# + Cluster: postgres (7123456789012345678) ----+----+-----------+
# | Member | Host          | Role    | State   | TL | Lag in MB |
# +--------+---------------+---------+---------+----+-----------+
# | node1  | 192.168.32.130| Leader  | running |  1 |           |
# | node2  | 192.168.32.131| Replica | running |  1 |         0 |
# +--------+---------------+---------+---------+----+-----------+
Step 5.2: Test HAProxy Routing
# Test connection through HAProxy
psql -h 192.168.32.135 -p 5000 -U postgres

# Create a test table
CREATE TABLE test_ha (id serial PRIMARY KEY, node_name text);

# Insert current node info
INSERT INTO test_ha (node_name) VALUES (inet_server_addr()::text);

# View results
SELECT * FROM test_ha;

# Exit
\q
Step 5.3: Test Read Replica Functionality
# Connect directly to node2 (replica)
psql -h 192.168.32.131 -p 5432 -U postgres

# Try to write (should fail on replica)
CREATE TABLE test_write (id int);

# You should see error: "cannot execute CREATE TABLE in a read-only transaction"
Step 5.4: Perform Failover Test
Scenario 1: Graceful Leader Stop

# On node1 (assuming it's the leader)
sudo systemctl stop patroni

# On node2, check cluster status
patronictl -c /etc/patroni.yml list

# node2 should now be the new leader

# Test HAProxy still routes to new leader
psql -h 192.168.32.135 -p 5000 -U postgres -c "SELECT inet_server_addr();"

# Restart node1
sudo systemctl start patroni

# Node1 should rejoin as replica
patronictl -c /etc/patroni.yml list
Scenario 2: Simulated Node Crash

# Find leader process
ps aux | grep postgres

# Force kill the leader process
sudo kill -9 <leader_pid>

# Check cluster recovery (on another node)
patronictl -c /etc/patroni.yml list

# New leader should be elected within 30 seconds
Step 5.5: Monitor HAProxy Statistics
Access the HAProxy statistics dashboard:

URL: http://192.168.32.135:7000
Username: admin
Password: admin
The dashboard shows:

Backend server status (green = up, red = down)
Session counts
Response times
Health check results
Part 6: Maintenance Operations
Backup Configuration
# Backup Patroni configuration
sudo cp /etc/patroni.yml /etc/patroni.yml.backup

# Backup HAProxy configuration
sudo cp /etc/haproxy/haproxy.cfg /etc/haproxy/haproxy.cfg.backup

# Backup etcd configuration
sudo cp /etc/default/etcd /etc/default/etcd.backup
Perform PostgreSQL Backup
# Backup from leader node
patronictl -c /etc/patroni.yml list
# Connect to leader and backup

pg_dumpall -h <leader_ip> -p 5432 -U postgres > backup.sql
Switchover (Manual Leader Change)
# Perform graceful switchover from node1 to node2
patronictl -c /etc/patroni.yml switchover

# Follow prompts to select target replica
Reboot Procedure
# To reboot a replica node safely:
sudo systemctl stop patroni
sudo reboot

# To reboot the leader node (perform switchover first):
patronictl -c /etc/patroni.yml switchover
# After switchover completes, reboot the old leader
Part 7: Troubleshooting Guide
Common Issues and Solutions
Issue 1: Patroni fails to start

# Check logs
sudo journalctl -u patroni -f

# Verify etcd connectivity
curl http://192.168.32.140:2379/version

# Check configuration syntax
python3 -c "import yaml; yaml.safe_load(open('/etc/patroni.yml'))"
Issue 2: PostgreSQL replication not working

# Check replication status on replica
psql -h 192.168.32.131 -U postgres -c "SELECT * FROM pg_stat_wal_receiver;"

# Check replication slots
psql -h 192.168.32.130 -U postgres -c "SELECT * FROM pg_replication_slots;"
Issue 3: HAProxy not routing correctly

# Check HAProxy logs
sudo tail -f /var/log/haproxy.log

# Verify health checks
curl http://192.168.32.130:8008/patroni
curl http://192.168.32.131:8008/patroni

# Check HAProxy status from stats page
curl http://localhost:7000/stats
Issue 4: etcd cluster issues

# Check etcd health
etcdctl endpoint health --endpoints=http://192.168.32.140:2379

# Check etcd logs
sudo journalctl -u etcd -f
Part 8: Monitoring and Alerts
Key Metrics to Monitor
Patroni	Leader Election	> 30 seconds	Alert
PostgreSQL	Replication Lag	> 100 MB	Investigate
HAProxy	Backend Health	Any DOWN	Immediate action
etcd	Cluster Health	Quorum lost	Critical
System	Disk Usage	> 80%	Plan expansion
Health Check Script
Create a monitoring script on haproxynode:

sudo nano /usr/local/bin/check_pg_ha.sh
#!/bin/bash

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
sudo chmod +x /usr/local/bin/check_pg_ha.sh
Set up Cron Job for Monitoring
sudo crontab -e

# Add the following line to check every 5 minutes
*/5 * * * * /usr/local/bin/check_pg_ha.sh >> /var/log/pg_ha_monitor.log
Part 9: Performance Optimization
PostgreSQL Performance Tuning
Add to postgresql section in patroni.yml:

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
HAProxy Performance Tuning
Update haproxy.cfg:

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
Conclusion
You have successfully configured a production-ready PostgreSQL High Availability cluster with:

✅ Automatic failover using Patroni
✅ Distributed consensus with etcd
✅ Load balancing with HAProxy
✅ Read replicas for workload distribution
✅ Health monitoring and statistics

Architecture Benefits
High Availability: Automatic failover within 30 seconds
No Single Point of Failure: Multiple components ensure reliability
Scalability: Easy to add more replicas
Transparent Failover: Applications connect to HAProxy, unaware of backend changes
Read Scaling: Can distribute read queries to replicas
Next Steps
Add more etcd nodes for production (minimum 3)
Configure SSL/TLS for all connections
Set up comprehensive monitoring (Prometheus + Grafana)
Implement backup strategy (pgBackRest or Barman)
Configure connection pooling using PgBouncer
Set up automated alerts (critical system events)
Important Production Notes
⚠️ Production Hardening Requirements:

Use separate etcd cluster (3 or 5 nodes)
Enable SSL/TLS for all services
Set up regular backups
Implement disaster recovery plan
Configure proper firewall rules
Use strong passwords (not the default ones from this guide)
Set up log rotation and monitoring
Appendix: Quick Reference Commands
Quick Status Checks
# Check Patroni cluster status
patronictl -c /etc/patroni.yml list

# Check etcd health
curl http://192.168.32.140:2379/health

# Check HAProxy stats
echo "show stat" | socat stdio /run/haproxy/admin.sock

# Check PostgreSQL replication lag
psql -U postgres -c "SELECT usename, application_name, state, sync_state, replay_lag FROM pg_stat_replication;"
Service Management
# Patroni
sudo systemctl [start|stop|restart|status] patroni

# etcd
sudo systemctl [start|stop|restart|status] etcd

# HAProxy
sudo systemctl [start|stop|restart|status] haproxy
Log File Locations
# Patroni logs
sudo journalctl -u patroni -f

# PostgreSQL logs
tail -f /data/patroni/log/postgresql-*.log

# etcd logs
sudo journalctl -u etcd -f

# HAProxy logs
sudo tail -f /var/log/haproxy.log
Document Version: 1.0
Last Updated: November 2024
Compatible with: Ubuntu 22.04, PostgreSQL 14, Patroni 3.0, HAProxy 2.4

For support or questions, refer to the official documentation:

Patroni Documentation
PostgreSQL Documentation
HAProxy Documentation
etcd Documentation