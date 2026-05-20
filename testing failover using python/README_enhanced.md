# Enhanced PostgreSQL HA Failover Test Script

This enhanced script provides comprehensive testing capabilities for PostgreSQL High Availability setups using Patroni, etcd, and HAProxy.

## Features

- **Multiple Test Types**: Insert, read, and mixed workload tests
- **Configurable Parameters**: Host, port, batch sizes, retry counts, etc.
- **Detailed Logging**: Comprehensive logging to both console and file
- **Automatic Setup/Cleanup**: Creates and drops test tables automatically
- **Performance Metrics**: Tracks insertion rates, read rates, and timing
- **Fault Tolerance**: Handles connection failures with exponential backoff
- **Command Line Interface**: Easy to configure via arguments

## Usage

### Basic Insert Test
```bash
python app_enhanced.py --host localhost --port 5000 --total-records 10000
```

### Read Test (1 minute duration)
```bash
python app_enhanced.py --host localhost --port 5000 --test-type read
```

### Mixed Workload Test
```bash
python app_enhanced.py --host localhost --port 5000 --test-type mixed --insert-ratio 0.7
```

### Custom Configuration
```bash
python app_enhanced.py \
  --host 192.168.32.134 \
  --port 5000 \
  --user postgres \
  --password password \
  --batch-size 500 \
  --max-retries 5 \
  --total-records 50000 \
  --log-level DEBUG
```

## Arguments

- `--host`: Database host (HAProxy/VIP) - default: localhost
- `--port`: Database port - default: 5000
- `--database`: Database name - default: postgres
- `--user`: Username - default: postgres
- `--password`: Password - default: password
- `--batch-size`: Batch size for inserts - default: 1000
- `--max-retries`: Max retries per batch - default: 10
- `--total-records`: Total records to insert - default: 500000
- `--log-level`: Logging level (DEBUG, INFO, WARNING, ERROR) - default: INFO
- `--test-type`: Type of test (insert, read, mixed) - default: insert
- `--table-name`: Table name for operations - default: employees
- `--insert-ratio`: Ratio of inserts in mixed workload (0.0-1.0) - default: 0.7

## Requirements

- Python 3.6+
- psycopg2-binary

Install requirements with:
```bash
pip install -r requirements_enhanced.txt
```

## Output

The script creates a log file with timestamp in the format:
`patroni_test_YYYYMMDD_HHMMSS.log`

The log file contains detailed information about:
- Connection attempts
- Batch processing results
- Retry attempts and delays
- Performance metrics
- Final verification counts

## Exit Codes

- 0: Test completed successfully
- 1: Test failed or was interrupted

## Notes

1. The script automatically creates a test table and drops it after completion
2. For read and mixed tests, ensure there's existing data in the table
3. The VIP address (192.168.32.134) should be used for testing failover scenarios
4. Monitor HAProxy stats at http://haproxy_ip:7000 during tests