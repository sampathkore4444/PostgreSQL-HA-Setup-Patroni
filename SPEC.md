# High Availability PostgreSQL Setup with Patroni, etcd, and HAProxy on Ubuntu Linux

This document provides a step-by-step guide to setting up a highly available PostgreSQL cluster using Patroni for automatic failover, etcd as the distributed configuration store, and HAProxy for load balancing and connection pooling. The setup is designed for bare-metal Ubuntu Linux servers (no Docker).

## Architecture Overview

- **etcd Cluster**: 3-node etcd cluster for storing Patroni configuration and leader election. (Does NOT run Patroni)
- **PostgreSQL Nodes**: 2+ PostgreSQL instances managed by Patroni (at least 2 for HA, 3 recommended). Patroni runs on these nodes.
- **HAProxy**: Load balancer that routes traffic to the current PostgreSQL leader and provides health checks.
- **Virtual IP (Optional)**: For seamless application failover, a virtual IP can be used with keepalived (covered in this spec).

> **Note**: Patroni runs exclusively on PostgreSQL nodes to manage PostgreSQL clusters. etcd nodes only run the etcd service for distributed consensus and do not run Patroni or PostgreSQL unless explicitly configured to do so (not recommended for production).

## Prerequisites

- Ubuntu Linux 20.04 LTS or 22.04 LTS (minimum 2GB RAM, 2 CPU cores per node recommended)
- **Server Roles**:
    - **etcd Cluster**: Requires 3 servers (can be separate or combined with PostgreSQL nodes, but Patroni does NOT run on etcd-only nodes).
    - **PostgreSQL/Patroni Nodes**: Requires 2+ servers (Patroni runs on these nodes to manage PostgreSQL).
    - **HAProxy**: Can be on a dedicated server or co-located with PostgreSQL/Patroni nodes (but dedicated is recommended for HA).
    - **Virtual IP (Optional)**: Requires 2 HAProxy servers for VIP failover (can be same as HAProxy servers above).
- sudo privileges on all servers.
- Static IP addresses or DHCP reservations for all servers.
- Open ports:
  - etcd: 2379 (peer), 2380 (client)
  - Patroni: 8008 (REST API), 5432 (PostgreSQL)
  - HAProxy: 5000 (PostgreSQL load balanced), 7000 (stats)
  - keepalived (VRRP): Protocol 112 (VRRP) must be allowed between HAProxy nodes for VIP

## Step 1: Prepare the Servers

### 1.1 Update and Install Dependencies

On all servers (etcd, PostgreSQL, HAProxy):

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y curl gnupg2 lsb-release
```

### 1.2 Create a Non-root User (Optional but Recommended)

```bash
sudo adduser --ingroup sudo patroni
sudo su - patroni
```

We'll use the `patroni` user for running Patroni and PostgreSQL. Adjust as needed.

## Step 2: Install and Configure etcd Cluster

We'll set up a 3-node etcd cluster. Repeat these steps on each etcd node, adjusting the node name and IP addresses.
> **Note**: etcd nodes only run the etcd service. Patroni does NOT run on etcd nodes unless you specifically configure them to also run PostgreSQL (not recommended for production HA).

### 2.1 Download and Install etcd

```bash
# On each etcd node
ETCD_VERSION=v3.5.9
curl -L https://github.com/etcd-io/etcd/releases/download/${ETCD_VERSION}/etcd-${ETCD_VERSION}-linux-amd64.tar.gz -o /tmp/etcd-${ETCD_VERSION}-linux-amd64.tar.gz
tar xzvf /tmp/etcd-${ETCD_VERSION}-linux-amd64.tar.gz
sudo mv etcd-${ETCD_VERSION}-linux-amd64/etcd* /usr/local/bin/
```

### 2.2 Create etcd User and Directories

```bash
sudo useradd -r -s /bin/nologin etcd
sudo mkdir -p /var/lib/etcd
sudo chown -R etcd:etcd /var/lib/etcd
```

### 2.3 Create etcd Configuration File

Create `/etc/etcd/etcd.conf.yml` with the following content (adjust `NAME`, `INTERNAL_IP`, and peer/client addresses for each node):

```yaml
name: etcd-node-1
data-dir: /var/lib/etcd
listen-peer-urls: http://INTERNAL_IP:2380
listen-client-urls: http://INTERNAL_IP:2379,http://127.0.0.1:2379
advertise-client-urls: http://INTERNAL_IP:2379
initial-advertise-peer-urls: http://INTERNAL_IP:2380
initial-cluster: etcd-node-1=http://ETCD_NODE_1_IP:2380,etcd-node-2=http://ETCD_NODE_2_IP:2380,etcd-node-3=http://ETCD_NODE_3_IP:2380
initial-cluster-token: etcd-cluster-1
initial-cluster-state: new
```

Replace:
- `etcd-node-1` with unique name for each node (etcd-node-1, etcd-node-2, etcd-node-3)
- `INTERNAL_IP` with the server's internal IP address
- `ETCD_NODE_X_IP` with the respective IP addresses of each etcd node

### 2.4 Create systemd Service File

Create `/etc/systemd/system/etcd.service`:

```ini
[Unit]
Description=etcd key-value store
Documentation=https://github.com/etcd-io/etcd
After=network.target

[Service]
Type=notify
User=etcd
ExecStart=/usr/local/bin/etcd --config-file /etc/etcd/etcd.conf.yml
Restart=on-failure
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

### 2.5 Start and Enable etcd

```bash
sudo systemctl daemon-reload
sudo systemctl enable etcd
sudo systemctl start etcd
sudo systemctl status etcd
```

Verify cluster health:

```bash
etcdctl endpoint health --cluster
```

## Step 3: Install and Configure Patroni on PostgreSQL Nodes

Repeat these steps on each PostgreSQL node that will run Patroni.

### 3.1 Install Dependencies

```bash
sudo apt install -y python3-pip python3-dev libpq-dev postgresql postgresql-contrib
```

### 3.2 Install Patroni and etcd Client

```bash
sudo pip3 install patroni[etcd]
```

### 3.3 Create PostgreSQL Data Directory

```bash
sudo mkdir -p /var/lib/postgresql/data
sudo chown -R patroni:patroni /var/lib/postgresql/data
```

### 3.4 Create Patroni Configuration File

Create `/etc/patroni.yml` with the following content (adjust for each node):

```yaml
scope: ha-postgres
name: _HOSTNAME_

restapi:
    listen: 0.0.0.0:8008
    connect_address: _HOSTNAME_:8008
    auth: patroni:patroni

etcd:
    host: ETCD_NODE_1_IP:2379,ETCD_NODE_2_IP:2379,ETCD_NODE_3_IP:2379

bootstrap:
    dcs:
        ttl: 30
        loop_wait: 10
        retry_timeout: 10
        maximum_lag_on_failover: 1048576
        postgresql:
            use_pg_rewind: true
            parameters:
                archive_mode: always
                archive_command: 'cd .'
                max_connections: 200
                shared_buffers: 256MB
                effective_cache_size: 768MB
                maintenance_work_mem: 64MB
                checkpoint_completion_target: 0.9
                wal_buffers: 16MB
                default_statistics_target: 100
                random_page_cost: 1.1
                effective_io_concurrency: 200
                work_mem: 6553kB
                min_wal_size: 1GB
                max_wal_size: 4GB
    initdb:
    - encoding: UTF8
    - data-checksums
    pg_hba:
    - local all all trust
    - host replication replicator 127.0.0.1/32 trust
    - host replication replicator 0.0.0.0/0 md5
    - host all all 127.0.0.1/32 trust
    - host all all 0.0.0.0/0 md5

postgresql:
    listen: 0.0.0.0:5432
    connect_address: _HOSTNAME_:5432
    data_dir: /var/lib/postgresql/data
    pgpass: /home/patroni/.pgpass
    authentication:
        replication:
            username: replicator
            password: replicator_password
        superuser:
            username: postgres
            password: postgres_password
    parameters:
        unix_socket_directories: '.'

tags:
    nofailover: false
    noloadbalance: false
    clonefrom: false
    nosync: false
```

Replace:
- `_HOSTNAME_`: Patroni will automatically replace this with the hostname (or set explicitly).
- `ETCD_NODE_X_IP`: The IP addresses of your etcd nodes.
- `replicator_password`, `postgres_password`: Set strong passwords.

### 3.5 Create systemd Service File for Patroni

Create `/etc/systemd/system/patroni.service`:

```ini
[Unit]
Description=Runners to orchestrate a high-availability PostgreSQL
After=network.target

[Service]
Type=simple
User=patroni
Group=patroni
ExecStart=/usr/local/bin/patroni /etc/patroni.yml
KillMode=process
TimeoutSec=30
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### 3.6 Start and Enable Patroni

```bash
sudo systemctl daemon-reload
sudo systemctl enable patroni
sudo systemctl start patroni
sudo systemctl status patroni
```

Check Patroni status:

```bash
patronictl -c /etc/patroni.yml list
```

You should see one node as leader and others as replicas.

## Step 4: Install and Configure HAProxy (on both HAProxy nodes)

HAProxy should be installed on two dedicated servers (or co-located with PostgreSQL/Patroni nodes if necessary) for high availability. These two HAProxy nodes will work together with keepalived to provide a virtual IP that fails over between them.

### 4.1 Install HAProxy on both nodes

```bash
sudo apt install -y haproxy
```

### 4.2 Configure HAProxy (identically on both nodes)

Edit `/etc/haproxy/haproxy.cfg` on both HAProxy servers:

```ini
global
    log /dev/log    local0
    log /dev/log    local1 notice
    daemon
    maxconn 2000
    user haproxy
    group haproxy

defaults
    log     global
    mode    tcp
    option  tcplog
    option  dontlognull
    retries 3
    timeout connect 5s
    timeout client  30s
    timeout server  30s

listen stats
    bind *:7000
    mode http
    stats enable
    stats uri /
    stats realm HAProxy\ Statistics
    stats auth admin:admin_password
    stats refresh 5s

listen postgres
    bind *:5000
    mode tcp
    option tcplog
    balance roundrobin
    option httpchk
    http-check expect status 200
    default-server inter 3s fall 3 rise 2 on-marked-down shutdown-sessions
    server postgres1 POSTGRES_NODE_1_IP:5432 check port 8008
    server postgres2 POSTGRES_NODE_2_IP:5432 check port 8008
    # Add more servers as needed
```

Replace:
- `POSTGRES_NODE_X_IP`: The IP addresses of your PostgreSQL/Patroni nodes.
- `admin_password`: Set a strong password for HAProxy stats.

> **Important**: The HAProxy configuration must be identical on both nodes.

### 4.3 Enable and Start HAProxy on both nodes

```bash
sudo systemctl enable haproxy
sudo systemctl restart haproxy
sudo systemctl status haproxy
```

### 4.4 (Optional) Configure Virtual IP with keepalived (on both HAProxy nodes)

For seamless application failover without requiring clients to reconnect, you can configure a virtual IP (VIP) using keepalived. This VIP will automatically move to the active HAProxy node.

#### 4.4.1 Install keepalived on both HAProxy nodes

```bash
sudo apt install -y keepalived
```

#### 4.4.2 Configure keepalived on both HAProxy nodes

Create `/etc/keepalived/keepalived.conf` on both HAProxy nodes with the following content:

```ini
! Configuration File for keepalived

global_defs {
   router_id HAProxy_VIP
}

vrrp_instance VI_1 {
    # On the PRIMARY HAProxy node, set state to MASTER and priority to 100
    # On the BACKUP HAProxy node, set state to BACKUP and priority to 90
    state MASTER  # Change to BACKUP on the backup node
    interface eth0  # Change to your network interface (e.g., ens5, enp0s3)
    virtual_router_id 51
    priority 100  # Set to 100 on primary, 90 on backup
    advert_int 1
    authentication {
        auth_type PASS
        auth_pass 1111  # Change to a strong secret
    }
    virtual_ipaddress {
        192.168.1.100/24 dev eth0 label eth0:vip  # Change to your VIP and interface
    }
}
```

Replace on each node appropriately:
- `interface eth0`: Your network interface name (use `ip addr show` to find)
- `state`: Set to `MASTER` on the primary HAProxy node, `BACKUP` on the backup node
- `priority`: Set to `100` on the primary HAProxy node, `90` on the backup node
- `virtual_ipaddress`: Your desired VIP address and interface (must be in same subnet as your HAProxy nodes)
- `auth_pass`: A strong secret password for VRRP authentication (must be same on both nodes)

#### 4.4.3 Enable and Start keepalived on both nodes

```bash
sudo systemctl enable keepalived
sudo systemctl restart keepalived
sudo systemctl status keepalived
```

Verify the VIP is assigned on the primary node:
```bash
ip addr show eth0
```

You should see the VIP address (e.g., 192.168.1.100) on the primary HAProxy node.

Applications should now connect to the VIP address (e.g., 192.168.1.100:5000) instead of directly to HAProxy.

## Step 5: Testing the Setup

### 5.1 Verify Patroni Leader

From any Patroni node:

```bash
patronictl -c /etc/patroni.yml list
```

### 5.2 Verify HAProxy is Routing to Leader

Connect to HAProxy port 5000 and check which node is accepting writes. You can also check HAProxy stats at `http://HAProxy_IP:7000`.

### 5.3 Simulate Failover

Stop the Patroni service on the leader node:

```bash
sudo systemctl stop patroni
```

Wait a few seconds, then check the Patroni cluster again. A new leader should be elected. Verify that HAProxy now routes to the new leader.

### 5.4 Test Connection from Application

Applications should connect to the Virtual IP address (if configured) or to either HAProxy node directly:
- With VIP: Connect to `VIP_ADDRESS:5000`
- Without VIP: Connect to `HAProxy_NODE_1_IP:5000` or `HAProxy_NODE_2_IP:5000`

### 5.5 Test Virtual IP Failover (if configured)

Stop keepalived on the primary HAProxy node:
```bash
sudo systemctl stop keepalived
```
Verify that the VIP has moved to the secondary HAProxy node by checking:
```bash
ip addr show eth0
```
On the primary node, the VIP should no longer be present.
On the secondary node, the VIP should now be present (may take a few seconds).
Applications should continue to connect via the VIP without interruption.

### 5.6 Test HAProxy Failover (without VIP)

Stop HAProxy on the active node:
```bash
sudo systemctl stop haproxy
```
Verify that connections to the stopped node fail, but connections to the other HAProxy node continue to work.
Applications should be configured to retry or use both HAProxy nodes for true HA without VIP.

## Step 6: Security Considerations

- Change all default passwords (etcd, Patroni, PostgreSQL, HAProxy).
- Consider enabling TLS for etcd, Patroni REST API, and HAProxy.
- Restrict network access to etcd (ports 2379, 2380) and Patroni (port 8008) to trusted networks only.
- Use firewalls (ufw) to limit access.

## Step 7: Maintenance and Monitoring

- Regularly backup PostgreSQL data (using `pg_basebackup` or file-level backups).
- Monitor etcd cluster health.
- Monitor Patroni logs (`journalctl -u patroni`).
- Monitor HAProxy logs (`/var/log/haproxy.log`).

## Troubleshooting

- **etcd not forming cluster**: Check firewalls, IP addresses in `initial-cluster`, and etcd logs.
- **Patroni cannot connect to etcd**: Verify etcd client URLs and network connectivity.
- **HAProxy not seeing Patroni nodes**: Ensure Patroni REST API is accessible on port 8008 and returns 200 for `/`.
- **PostgreSQL authentication issues**: Check `pg_hba.conf` and `.pgpass` files.
- **VIP not moving between HAProxy nodes**: Check keepalived logs (`journalctl -u keepalived`), verify VRRP protocol (112) is allowed between nodes, and ensure priorities are set correctly.
- **Applications cannot connect via VIP**: Verify VIP address is assigned to an interface (`ip addr show`), check HAProxy is listening on port 5000, and ensure no firewall blocks the VIP.
- **HAProxy nodes not synchronized**: Ensure both HAProxy nodes have identical configuration, especially the `listen postgres` section and stats configuration.
- **One HAProxy node not responding**: Check HAProxy service status (`systemctl status haproxy`), logs (`/var/log/haproxy.log`), and verify it's bound to port 5000 (`ss -tlnp | grep 5000`).

## Conclusion

This setup provides a robust highly available PostgreSQL cluster using Patroni, etcd, and HAProxy on Ubuntu Linux without Docker. For production, consider adding monitoring, logging, and regular backups. The optional Virtual IP with keepalived (configured on two HAProxy nodes) provides seamless application failover without requiring clients to reconnect during HAProxy failover. Even without VIP, using two HAProxy nodes allows applications to retry connections to the backup node if the primary fails.

---
*Spec generated for Loma POCs Postgres HA Setup*