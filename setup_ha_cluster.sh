#!/bin/bash
# PostgreSQL HA Cluster Setup Script
# Based on HA_Notes_Final.md documentation

set -e  # Exit on any error

echo "=== PostgreSQL HA Cluster Setup ==="
echo "This script will help you set up a PostgreSQL HA cluster with Patroni, etcd, and HAProxy"
echo "Please review and configure the variables below before running."

# =========================================================
# CONFIGURATION - UPDATE THESE VALUES FOR YOUR ENVIRONMENT
# =========================================================

# Server IP addresses (update these to match your environment)
NODE1_IP="192.168.32.130"      # PostgreSQL Primary/Leader
NODE2_IP="192.168.32.131"      # PostgreSQL Replica/Standby
ETCD_IP="192.168.32.140"       # etcd cluster node
HAPROXY1_IP="192.168.32.135"   # HAProxy Active/Primary
HAPROXY2_IP="192.168.32.136"   # HAProxy Standby/Backup
VIP="192.168.32.134"           # Virtual IP for HAProxy failover

# Hostnames
NODE1_HOSTNAME="node1"
NODE2_HOSTNAME="node2"
ETCD_HOSTNAME="etcdnode"
HAPROXY1_HOSTNAME="haproxynode1"
HAPROXY2_HOSTNAME="haproxynode2"

# Passwords (UPDATE THESE FOR PRODUCTION!)
ETCD_PASSWORD="etcd_password"
POSTGRES_PASSWORD="postgres_password"
REPLICATOR_PASSWORD="replicator_password"
PATRONI_ADMIN_PASSWORD="patroni_admin_password"
HAPROXY_STATS_PASSWORD="haproxy_stats_password"
KEEPALIVED_PASSWORD="keepalived_password"

# Network interface (update if different)
NETWORK_INTERFACE="eth0"

# =========================================================
# FUNCTIONS
# =========================================================

log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1"
}

error() {
    log "ERROR: $1"
    exit 1
}

confirm() {
    read -p "$1 (y/N): " response
    case "$response" in
        [yY][eE][sS]|[yY])
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

# =========================================================
# MAIN SCRIPT
# =========================================================

log "Starting PostgreSQL HA cluster setup..."
log "Please ensure you have 5 Ubuntu 22.04 servers ready with the following IPs:"
log "  node1: $NODE1_IP"
log "  node2: $NODE2_IP"
log "  etcdnode: $ETCD_IP"
log "  haproxynode1: $HAPROXY1_IP"
log "  haproxynode2: $HAPROXY2_IP"
log "  VIP: $VIP"

if ! confirm "Do you want to continue with these settings?"; then
    log "Setup cancelled by user."
    exit 1
fi

log "=== Setup Instructions ==="
log "This script provides automated commands for each step."
log "You will need to run these commands on each respective server."
log ""
log "IMPORTANT: Review the HA_Notes_Final.md file for detailed explanations."
log ""

# =========================================================
# PART 1: ETCD CLUSTER SETUP
# =========================================================
log "=== PART 1: Configure etcd Cluster (on $ETCD_IP) ==="
log "Run these commands on etcdnode ($ETCD_IP):"
cat << EOF
# Step 1.1: Update System and Install Dependencies
sudo apt update -y
sudo apt install -y net-tools wget curl gnupg lsb-release

# Step 1.2: Configure Hostname
sudo hostnamectl set-hostname $ETCD_HOSTNAME
sudo bash -c 'cat << HOSTS_EOF >> /etc/hosts
$NODE1_IP $NODE1_HOSTNAME
$NODE2_IP $NODE2_HOSTNAME
$ETCD_IP $ETCD_HOSTNAME
$HAPROXY1_IP $HAPROXY1_HOSTNAME
$HAPROXY2_IP $HAPROXY2_HOSTNAME
$VIP vip
HOSTS_EOF'

# Step 1.3: Install etcd
sudo apt install -y etcd

# Step 1.4: Configure etcd
sudo bash -c 'cat > /etc/default/etcd << ETCD_EOF
# etcd configuration for single node cluster
ETCD_LISTEN_PEER_URLS="http://$ETCD_IP:2380"
ETCD_LISTEN_CLIENT_URLS="http://localhost:2379,http://$ETCD_IP:2379"
ETCD_INITIAL_ADVERTISE_PEER_URLS="http://$ETCD_IP:2380"
ETCD_INITIAL_CLUSTER="default=http://$ETCD_IP:2380"
ETCD_ADVERTISE_CLIENT_URLS="http://$ETCD_IP:2379"
ETCD_INITIAL_CLUSTER_TOKEN="etcd-cluster"
ETCD_INITIAL_CLUSTER_STATE="new"
ETCD_EOF'

# Step 1.5: Start and Validate etcd
sudo systemctl restart etcd
sudo systemctl enable etcd
sudo systemctl status etcd
curl http://$ETCD_IP:2379/version
curl http://$ETCD_IP:2380/members
EOF

# =========================================================
# PART 2: PATRONI ON NODE1
# =========================================================
log ""
log "=== PART 2: Configure Patroni on PostgreSQL Node 1 (on $NODE1_IP) ==="
log "Run these commands on node1 ($NODE1_IP):"
cat << EOF
# Step 2.1: System Preparation
sudo apt update -y
sudo apt install -y net-tools wget curl
sudo hostnamectl set-hostname $NODE1_HOSTNAME
sudo bash -c 'cat << HOSTS_EOF >> /etc/hosts
$NODE1_IP $NODE1_HOSTNAME
$NODE2_IP $NODE2_HOSTNAME
$ETCD_IP $ETCD_HOSTNAME
$HAPROXY1_IP $HAPROXY1_HOSTNAME
$HAPROXY2_IP $HAPROXY2_HOSTNAME
$VIP vip
HOSTS_EOF'

# Step 2.2: Install PostgreSQL
sudo apt install -y postgresql postgresql-server-dev-14 postgresql-client-14
sudo systemctl stop postgresql
sudo systemctl disable postgresql
sudo rm -rf /var/lib/postgresql/14/main

# Step 2.3: Link PostgreSQL Binaries
sudo ln -s /usr/lib/postgresql/14/bin/* /usr/sbin/
ls -la /usr/sbin/ | grep postgres

# Step 2.4: Install Python and Patroni
sudo apt install -y python3 python3-pip python3-venv
sudo pip3 install --upgrade pip setuptools
sudo pip3 install patroni python-etcd psycopg2-binary

# Step 2.5: Create Patroni Data Directory
sudo mkdir -p /data/patroni
sudo chown postgres:postgres /data/patroni
sudo chmod 750 /data/patroni

# Step 2.6: Configure Patroni
sudo bash -c 'cat > /etc/patroni.yml << PATRONI_EOF
scope: postgres
namespace: /db/
name: $NODE1_HOSTNAME

restapi:
    listen: $NODE1_IP:8008
    connect_address: $NODE1_IP:8008

etcd:
    host: $ETCD_IP:2379

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
    - host replication replicator $NODE1_IP/0 md5
    - host replication replicator $NODE2_IP/0 md5
    - host all all 0.0.0.0/0 md5
    users:
      admin:
        password: $PATRONI_ADMIN_PASSWORD
        options:
          - createrole
          - createdb

postgresql:
  listen: $NODE1_IP:5432
  connect_address: $NODE1_IP:5432
  data_dir: /data/patroni
  pgpass: /tmp/pgpass
  authentication:
    replication:
      username: replicator
      password: $REPLICATOR_PASSWORD
    superuser:
      username: postgres
      password: $POSTGRES_PASSWORD
  parameters:
    unix_socket_directories: '.'

tags:
    nofailover: false
    noloadbalance: false
    clonefrom: false
    nosync: false
PATRONI_EOF'

# Step 2.7: Create Systemd Service for Patroni
sudo bash -c 'cat > /etc/systemd/system/patroni.service << PATRONI_SERVICE_EOF
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
PATRONI_SERVICE_EOF'

# Step 2.8: Start Patroni Service
sudo systemctl daemon-reload
sudo systemctl start patroni
sudo systemctl enable patroni
sudo systemctl status patroni

# Step 2.9: Verify Patroni Installation
patronictl -c /etc/patroni.yml list
curl http://$NODE1_IP:8008/patroni
EOF

# =========================================================
# PART 3: PATRONI ON NODE2
# =========================================================
log ""
log "=== PART 3: Configure Second PostgreSQL Node (on $NODE2_IP) ==="
log "Run these commands on node2 ($NODE2_IP):"
cat << EOF
# Step 3.1: System Preparation
sudo apt update -y
sudo apt install -y net-tools wget curl
sudo hostnamectl set-hostname $NODE2_HOSTNAME
sudo bash -c 'cat << HOSTS_EOF >> /etc/hosts
$NODE1_IP $NODE1_HOSTNAME
$NODE2_IP $NODE2_HOSTNAME
$ETCD_IP $ETCD_HOSTNAME
$HAPROXY1_IP $HAPROXY1_HOSTNAME
$HAPROXY2_IP $HAPROXY2_HOSTNAME
$VIP vip
HOSTS_EOF'

# Step 3.2: Install PostgreSQL and Patroni
sudo apt install -y postgresql postgresql-server-dev-14 postgresql-client-14
sudo systemctl stop postgresql
sudo systemctl disable postgresql
sudo rm -rf /var/lib/postgresql/14/main
sudo ln -s /usr/lib/postgresql/14/bin/* /usr/sbin/
sudo apt install -y python3 python3-pip
sudo pip3 install --upgrade pip setuptools
sudo pip3 install patroni python-etcd psycopg2-binary
sudo mkdir -p /data/patroni
sudo chown postgres:postgres /data/patroni
sudo chmod 750 /data/patroni

# Step 3.3: Configure Patroni for node2
sudo bash -c 'cat > /etc/patroni.yml << PATRONI_EOF
scope: postgres
namespace: /db/
name: $NODE2_HOSTNAME

restapi:
    listen: $NODE2_IP:8008
    connect_address: $NODE2_IP:8008

etcd:
    host: $ETCD_IP:2379

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
    - host replication replicator $NODE1_IP/0 md5
    - host replication replicator $NODE2_IP/0 md5
    - host all all 0.0.0.0/0 md5
    users:
      admin:
        password: $PATRONI_ADMIN_PASSWORD
        options:
          - createrole
          - createdb

postgresql:
  listen: $NODE2_IP:5432
  connect_address: $NODE2_IP:5432
  data_dir: /data/patroni
  pgpass: /tmp/pgpass
  authentication:
    replication:
      username: replicator
      password: $REPLICATOR_PASSWORD
    superuser:
      username: postgres
      password: $POSTGRES_PASSWORD
  parameters:
    unix_socket_directories: '.'

tags:
    nofailover: false
    noloadbalance: false
    clonefrom: false
    nosync: false
PATRONI_EOF'

# Step 3.4: Create and Start Patroni Service
sudo bash -c 'cat > /etc/systemd/system/patroni.service << PATRONI_SERVICE_EOF
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
PATRONI_SERVICE_EOF'

sudo systemctl daemon-reload
sudo systemctl start patroni
sudo systemctl enable patroni
sudo systemctl status patroni
EOF

# =========================================================
# PART 4: HAPROXY SETUP
# =========================================================
log ""
log "=== PART 4: Configure HAProxy (on $HAPROXY1_IP and $HAPROXY2_IP) ==="
log "Run these commands on BOTH haproxynode1 ($HAPROXY1_IP) and haproxynode2 ($HAPROXY2_IP):"
cat << EOF
# Step 4.1: Install HAProxy
sudo apt update -y
sudo apt install -y haproxy net-tools curl

# Set hostname (run ONLY on the respective node)
# On haproxynode1: sudo hostnamectl set-hostname $HAPROXY1_HOSTNAME
# On haproxynode2: sudo hostnamectl set-hostname $HAPROXY2_HOSTNAME

sudo bash -c 'cat << HOSTS_EOF >> /etc/hosts
$NODE1_IP $NODE1_HOSTNAME
$NODE2_IP $NODE2_HOSTNAME
$ETCD_IP $ETCD_HOSTNAME
$HAPROXY1_IP $HAPROXY1_HOSTNAME
$HAPROXY2_IP $HAPROXY2_HOSTNAME
$VIP vip
HOSTS_EOF'

# Step 4.2: Configure HAProxy
sudo cp /etc/haproxy/haproxy.cfg /etc/haproxy/haproxy.cfg.backup
sudo bash -c 'cat > /etc/haproxy/haproxy.cfg << HAPROXY_EOF
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
    stats auth admin:$HAPROXY_STATS_PASSWORD
    stats refresh 30s

# PostgreSQL Load Balancer
listen postgres
    bind *:5000
    mode tcp
    option httpchk OPTIONS /master
    http-check expect status 200
    default-server inter 3s fall 3 rise 2 on-marked-down shutdown-sessions
    server node1 $NODE1_IP:5432 maxconn 100 check port 8008
    server node2 $NODE2_IP:5432 maxconn 100 check port 8008
HAPROXY_EOF'

# Step 4.3: Start HAProxy
sudo haproxy -f /etc/haproxy/haproxy.cfg -c
sudo systemctl start haproxy
sudo systemctl enable haproxy
sudo systemctl status haproxy
sudo systemctl restart haproxy

# Step 4.4: Verify HAProxy
sudo netstat -tlnp | grep haproxy
curl http://localhost:7000
psql -h $HAPROXY1_IP -p 5000 -U postgres -c "SELECT version();"
EOF

# =========================================================
# PART 5: KEEPALIVED SETUP
# =========================================================
log ""
log "=== PART 5: Configure keepalived for HAProxy Failover ==="
log "Run these commands on haproxynode1 ($HAPROXY1_IP) - PRIMARY/MASTER:"
cat << EOF
# Step 5.1: Install keepalived
sudo apt install -y keepalived

# Step 5.2: Configure keepalived (PRIMARY)
sudo bash -c 'cat > /etc/keepalived/keepalived.conf << KEEPALIVED_EOF
! Configuration File for keepalived

global_defs {
   router_id HAProxy_VIP
}

vrrp_instance VI_1 {
    state MASTER
    interface $NETWORK_INTERFACE
    virtual_router_id 51
    priority 100
    advert_int 1
    authentication {
        auth_type PASS
        auth_pass $KEEPALIVED_PASSWORD
    }
    virtual_ipaddress {
        $VIP/24 dev $NETWORK_INTERFACE label $NETWORK_INTERFACE:vip
    }
}
KEEPALIVED_EOF'

# Step 5.3: Start and Enable keepalived
sudo systemctl enable keepalived
sudo systemctl start keepalived
sudo systemctl status keepalived

# Step 5.4: Verify VIP Assignment
ip addr show $NETWORK_INTERFACE
EOF

log ""
log "Run these commands on haproxynode2 ($HAPROXY2_IP) - BACKUP:"
cat << EOF
# Step 5.1: Install keepalived
sudo apt install -y keepalived

# Step 5.2: Configure keepalived (BACKUP)
sudo bash -c 'cat > /etc/keepalived/keepalived.conf << KEEPALIVED_EOF
! Configuration File for keepalived

global_defs {
   router_id HAProxy_VIP
}

vrrp_instance VI_1 {
    state BACKUP
    interface $NETWORK_INTERFACE
    virtual_router_id 51
    priority 90
    advert_int 1
    authentication {
        auth_type PASS
        auth_pass $KEEPALIVED_PASSWORD
    }
    virtual_ipaddress {
        $VIP/24 dev $NETWORK_INTERFACE label $NETWORK_INTERFACE:vip
    }
}
KEEPALIVED_EOF'

# Step 5.3: Start and Enable keepalived
sudo systemctl enable keepalived
sudo systemctl start keepalived
sudo systemctl status keepalived

# Step 5.4: Verify VIP Assignment (should NOT show VIP initially)
ip addr show $NETWORK_INTERFACE
EOF

# =========================================================
# PART 6: TESTING AND VALIDATION
# =========================================================
log ""
log "=== PART 6: Testing and Validation ==="
log "After completing all setup steps above, run these validation tests:"
cat << EOF
# Step 6.1: Check Cluster Status (run on either node1 or node2)
patronictl -c /etc/patroni.yml list

# Expected output should show one node as Leader and one as Replica

# Step 6.2: Test Connection via VIP
psql -h $VIP -p 5000 -U postgres
# Inside psql:
CREATE TABLE test_ha (id serial PRIMARY KEY, node_name text);
INSERT INTO test_ha (node_name) VALUES (inet_server_addr()::text);
SELECT * FROM test_ha;
\q

# Step 6.3: Test HAProxy Failover
# Stop HAProxy on active node and verify VIP moves to standby
# Then test connection through VIP still works

# Step 6.4: Perform Failover Test
# Stop patroni on leader and verify failover works
EOF

log ""
log "=== Setup Complete ==="
log "Next steps:"
log "1. Run the commands for each part on the appropriate servers"
log "2. Follow the testing and validation steps in Part 6"
log "3. Refer to HA_Notes_Final.md for detailed explanations and troubleshooting"
log ""
log "Remember to change all default passwords in a production environment!"
log "Consider enabling TLS for etcd, Patroni REST API, and HAProxy for production use."
EOF
