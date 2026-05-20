import time
import psycopg2
from psycopg2.extras import execute_values
from psycopg2 import OperationalError, InterfaceError, DatabaseError
import argparse
import sys
import logging
from datetime import datetime

# =========================================================
# CONFIG
# =========================================================


def parse_args():
    parser = argparse.ArgumentParser(description="PostgreSQL HA failover test script")
    parser.add_argument(
        "--host", default="localhost", help="Database host (HAProxy/VIP)"
    )
    parser.add_argument("--port", type=int, default=5000, help="Database port")
    parser.add_argument("--database", default="postgres", help="Database name")
    parser.add_argument("--user", default="postgres", help="Username")
    parser.add_argument("--password", default="password", help="Password")
    parser.add_argument(
        "--batch-size", type=int, default=1000, help="Batch size for inserts"
    )
    parser.add_argument(
        "--max-retries", type=int, default=10, help="Max retries per batch"
    )
    parser.add_argument(
        "--total-records", type=int, default=500000, help="Total records to insert"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )
    parser.add_argument(
        "--test-type",
        choices=["insert", "read", "mixed"],
        default="insert",
        help="Type of test to run",
    )
    parser.add_argument(
        "--table-name", default="employees", help="Table name for operations"
    )
    return parser.parse_args()


# Setup logging
def setup_logging(log_level):
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(
                f'patroni_test_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
            ),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger(__name__)


# =========================================================
# HELPERS
# =========================================================


def chunked(data, chunk_size):
    """
    Yield chunks from large list
    """
    for i in range(0, len(data), chunk_size):
        yield data[i : i + chunk_size]


def create_connection(db_config):
    """
    Create NEW DB connection
    """
    return psycopg2.connect(**db_config)


# =========================================================
# MAIN TEST FUNCTIONS
# =========================================================


def insert_with_retry(
    records,
    batch_size=1000,
    max_retries=10,
    db_config=None,
    logger=None,
    table_name="employees",
):
    """
    Insert records in batches with retry support
    for Patroni failover.
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    total_inserted = 0
    batch_number = 0
    start_time = time.time()

    for batch in chunked(records, batch_size):
        batch_number += 1
        batch_start = time.time()

        for attempt in range(max_retries):
            conn = None
            try:
                logger.info(f"Batch {batch_number} | Attempt {attempt + 1}")

                # Create NEW connection every retry
                conn = create_connection(db_config)
                conn.autocommit = False

                with conn.cursor() as cur:
                    execute_values(
                        cur,
                        f"""
                        INSERT INTO {table_name}
                        (name, age, salary)
                        VALUES %s
                        """,
                        batch,
                    )

                conn.commit()
                batch_time = time.time() - batch_start
                total_inserted += len(batch)

                logger.info(
                    f"SUCCESS: Batch {batch_number} inserted "
                    f"{len(batch)} rows "
                    f"(Total={total_inserted}) "
                    f"[Batch time: {batch_time:.2f}s]"
                )

                # Batch success -> stop retry loop
                break

            except (
                OperationalError,
                InterfaceError,
                DatabaseError,
            ) as e:
                logger.warning(
                    f"ERROR: Batch {batch_number} failed " f"on attempt {attempt + 1}"
                )
                logger.warning(f"Exception: {e}")

                # Rollback only if connection still alive
                if conn and not conn.closed:
                    try:
                        conn.rollback()
                    except Exception:
                        pass

                # If max retries reached
                if attempt == max_retries - 1:
                    logger.error(f"FAILED permanently after {max_retries} retries")
                    return False, total_inserted

                # Exponential backoff with jitter
                wait_time = min(2**attempt + (time.time() % 1), 30)
                logger.info(f"Waiting {wait_time:.2f} seconds before retry...")
                time.sleep(wait_time)

            except Exception as e:
                logger.error(f"UNEXPECTED ERROR: {e}")
                if conn and not conn.closed:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                return False, total_inserted

            finally:
                if conn and not conn.closed:
                    try:
                        conn.close()
                    except Exception:
                        pass

    total_time = time.time() - start_time
    logger.info(f"\nALL RECORDS INSERTED SUCCESSFULLY")
    logger.info(f"Total time: {total_time:.2f} seconds")
    logger.info(f"Average rate: {total_inserted/total_time:.2f} records/second")
    return True, total_inserted


def read_test(db_config, logger=None, table_name="employees", duration_seconds=60):
    """
    Perform read tests for specified duration
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    start_time = time.time()
    read_count = 0
    error_count = 0

    logger.info(f"Starting read test for {duration_seconds} seconds...")

    while time.time() - start_time < duration_seconds:
        conn = None
        try:
            conn = create_connection(db_config)
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM {table_name}")
                result = cur.fetchone()
                read_count += 1

                if read_count % 100 == 0:
                    logger.info(f"Read count: {read_count}, Latest count: {result[0]}")

        except Exception as e:
            error_count += 1
            logger.error(f"Read error: {e}")
        finally:
            if conn and not conn.closed:
                try:
                    conn.close()
                except Exception:
                    pass

        # Small delay to prevent overwhelming the system
        time.sleep(0.1)

    total_time = time.time() - start_time
    logger.info(
        f"Read test completed. Reads: {read_count}, Errors: {error_count}, Duration: {total_time:.2f}s"
    )
    logger.info(f"Average read rate: {read_count/total_time:.2f} reads/second")
    return read_count, error_count


def mixed_workload_test(
    records,
    batch_size=1000,
    max_retries=10,
    db_config=None,
    logger=None,
    table_name="employees",
    insert_ratio=0.7,
):
    """
    Mixed workload of inserts and reads
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    logger.info(f"Starting mixed workload test (insert ratio: {insert_ratio})")

    # Split records for inserts and prepare for reads
    insert_count = int(len(records) * insert_ratio)
    insert_records = records[:insert_count]

    total_inserted = 0
    batch_number = 0
    read_count = 0
    error_count = 0

    start_time = time.time()

    # Process insert batches
    for batch in chunked(insert_records, batch_size):
        batch_number += 1

        # Perform insert with retry
        success, inserted = insert_with_retry(
            [batch],  # Wrap in list to make it iterable of batches
            batch_size=len(batch),
            max_retries=max_retries,
            db_config=db_config,
            logger=logger,
            table_name=table_name,
        )

        if success:
            total_inserted += inserted
        else:
            logger.error(f"Failed to insert batch {batch_number}")

        # Occasionally perform a read
        if batch_number % 10 == 0:  # Every 10 batches
            conn = None
            try:
                conn = create_connection(db_config)
                with conn.cursor() as cur:
                    cur.execute(f"SELECT COUNT(*) FROM {table_name}")
                    result = cur.fetchone()
                    read_count += 1
                    logger.info(
                        f"Mixed workload - Read {read_count}: {result[0]} records in table"
                    )
            except Exception as e:
                error_count += 1
                logger.error(f"Mixed workload read error: {e}")
            finally:
                if conn and not conn.closed:
                    try:
                        conn.close()
                    except Exception:
                        pass

    total_time = time.time() - start_time
    logger.info(
        f"Mixed workload completed. Inserted: {total_inserted}, Reads: {read_count}, Errors: {error_count}"
    )
    logger.info(f"Total time: {total_time:.2f} seconds")
    return total_inserted, read_count, error_count


# =========================================================
# TEST DATA GENERATION
# =========================================================


def generate_test_data(record_count, name_prefix="Employee"):
    """
    Generate test data
    """
    logger = logging.getLogger(__name__)
    logger.info(f"Generating {record_count} test records...")
    records = [
        (f"{name_prefix} {i}", 20 + (i % 50), 30000 + (i % 100000))
        for i in range(record_count)
    ]
    logger.info(f"Generated {len(records)} records")
    return records


# =========================================================
# SETUP/CLEANUP
# =========================================================


def setup_database(db_config, table_name="employees", logger=None):
    """
    Setup test table
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    conn = None
    try:
        conn = create_connection(db_config)
        conn.autocommit = True
        with conn.cursor() as cur:
            # Drop table if exists and create fresh
            cur.execute(f"DROP TABLE IF EXISTS {table_name}")
            cur.execute(f"""
                CREATE TABLE {table_name} (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(100),
                    age INTEGER,
                    salary DECIMAL(10,2),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Create index for better read performance
            cur.execute(f"CREATE INDEX idx_{table_name}_name ON {table_name}(name)")
            logger.info(f"Table {table_name} created successfully")
    except Exception as e:
        logger.error(f"Failed to setup database: {e}")
        raise
    finally:
        if conn and not conn.closed:
            try:
                conn.close()
            except Exception:
                pass


def cleanup_database(db_config, table_name="employees", logger=None):
    """
    Cleanup test table
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    conn = None
    try:
        conn = create_connection(db_config)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {table_name}")
            logger.info(f"Table {table_name} cleaned up successfully")
    except Exception as e:
        logger.error(f"Failed to cleanup database: {e}")
    finally:
        if conn and not conn.closed:
            try:
                conn.close()
            except Exception:
                pass


# =========================================================
# MAIN EXECUTION
# =========================================================


def main():
    args = parse_args()
    logger = setup_logging(args.log_level)

    db_config = {
        "host": args.host,
        "port": args.port,
        "database": args.database,
        "user": args.user,
        "password": args.password,
        "connect_timeout": 10,
        "keepalives": 1,
        "keepalives_idle": 5,
        "keepalives_interval": 2,
        "keepalives_count": 2,
        "application_name": "patroni_ha_test",
    }

    logger.info("=== PostgreSQL HA Failover Test ===")
    logger.info(f"Configuration: {db_config}")
    logger.info(f"Test type: {args.test_type}")
    logger.info(f"Total records: {args.total_records}")
    logger.info(f"Batch size: {args.batch_size}")
    logger.info(f"Max retries: {args.max_retries}")

    try:
        # Setup database
        setup_database(db_config, args.table_name, logger)

        # Generate test data
        records = generate_test_data(args.total_records)

        start_time = time.time()
        success = False

        if args.test_type == "insert":
            success, total_inserted = insert_with_retry(
                records=records,
                batch_size=args.batch_size,
                max_retries=args.max_retries,
                db_config=db_config,
                logger=logger,
                table_name=args.table_name,
            )
            if success:
                logger.info(f"INSERT TEST SUCCESS: {total_inserted} records inserted")
            else:
                logger.error("INSERT TEST FAILED")

        elif args.test_type == "read":
            read_count, error_count = read_test(
                db_config=db_config,
                logger=logger,
                table_name=args.table_name,
                duration_seconds=60,  # 1 minute test
            )
            success = error_count == 0
            logger.info(f"READ TEST: {read_count} reads, {error_count} errors")

        elif args.test_type == "mixed":
            total_inserted, read_count, error_count = mixed_workload_test(
                records=records,
                batch_size=args.batch_size,
                max_retries=args.max_retries,
                db_config=db_config,
                logger=logger,
                table_name=args.table_name,
            )
            success = error_count == 0
            logger.info(
                f"MIXED WORKLOAD TEST: {total_inserted} inserted, {read_count} reads, {error_count} errors"
            )

        total_time = time.time() - start_time
        logger.info(f"Total test duration: {total_time:.2f} seconds")

        # Final verification
        conn = None
        try:
            conn = create_connection(db_config)
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM {args.table_name}")
                final_count = cur.fetchone()[0]
                logger.info(f"Final record count in table: {final_count}")
        except Exception as e:
            logger.error(f"Failed to get final count: {e}")
        finally:
            if conn and not conn.closed:
                try:
                    conn.close()
                except Exception:
                    pass

    except KeyboardInterrupt:
        logger.info("Test interrupted by user")
        success = False
    except Exception as e:
        logger.error(f"Unexpected error during test: {e}")
        success = False
    finally:
        # Cleanup
        try:
            cleanup_database(db_config, args.table_name, logger)
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
