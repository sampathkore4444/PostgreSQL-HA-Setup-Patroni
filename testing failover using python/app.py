import time
import psycopg2
from psycopg2.extras import execute_values
from psycopg2 import OperationalError, InterfaceError, DatabaseError

# =========================================================
# CONFIG
# =========================================================

DB_CONFIG = {
    # IMPORTANT:
    # This should be HAProxy / pgBouncer / VIP endpoint
    # NOT direct Patroni node
    "host": "localhost",
    "port": 5000,
    "database": "postgres",
    "user": "postgres",
    "password": "password",
    # Faster failure detection
    "connect_timeout": 10,
    # TCP keepalive settings
    "keepalives": 1,
    "keepalives_idle": 5,
    "keepalives_interval": 2,
    "keepalives_count": 2,
    "application_name": "patroni_bulk_insert",
}


# =========================================================
# HELPERS
# =========================================================


def chunked(data, chunk_size):
    """
    Yield chunks from large list
    """
    for i in range(0, len(data), chunk_size):
        yield data[i : i + chunk_size]


def create_connection():
    """
    Create NEW DB connection
    """
    return psycopg2.connect(**DB_CONFIG)


# =========================================================
# MAIN INSERT FUNCTION
# =========================================================


def insert_with_retry(
    records,
    batch_size=1000,
    max_retries=10,
):
    """
    Insert records in batches with retry support
    for Patroni failover.
    """

    total_inserted = 0
    batch_number = 0

    for batch in chunked(records, batch_size):

        batch_number += 1

        for attempt in range(max_retries):

            conn = None

            try:
                print(f"\nBatch {batch_number} | " f"Attempt {attempt + 1}")

                # Create NEW connection every retry
                conn = create_connection()

                conn.autocommit = False

                with conn.cursor() as cur:

                    execute_values(
                        cur,
                        """
                        INSERT INTO employees
                        (name, age, salary)
                        VALUES %s
                        """,
                        batch,
                    )

                conn.commit()

                total_inserted += len(batch)

                print(
                    f"SUCCESS: Batch {batch_number} inserted "
                    f"{len(batch)} rows "
                    f"(Total={total_inserted})"
                )

                # Batch success -> stop retry loop
                break

            except (
                OperationalError,
                InterfaceError,
                DatabaseError,
            ) as e:

                print(
                    f"ERROR: Batch {batch_number} failed " f"on attempt {attempt + 1}"
                )

                print(f"Exception: {e}")

                # Rollback only if connection still alive
                if conn and not conn.closed:
                    try:
                        conn.rollback()
                    except Exception:
                        pass

                # If max retries reached
                if attempt == max_retries - 1:
                    print(f"FAILED permanently after " f"{max_retries} retries")
                    return False

                # Exponential backoff
                wait_time = min(2**attempt, 30)

                print(f"Waiting {wait_time} seconds before retry...")

                time.sleep(wait_time)

            except Exception as e:

                print(f"UNEXPECTED ERROR: {e}")

                if conn and not conn.closed:
                    try:
                        conn.rollback()
                    except Exception:
                        pass

                return False

            finally:

                if conn and not conn.closed:
                    try:
                        conn.close()
                    except Exception:
                        pass

    print("\nALL RECORDS INSERTED SUCCESSFULLY")
    return True


# =========================================================
# TEST DATA
# =========================================================

if __name__ == "__main__":

    # Create sample records
    records = [(f"Employee {i}", 25, 50000) for i in range(500000)]

    start = time.time()

    success = insert_with_retry(
        records=records,
        batch_size=1000,
        max_retries=10,
    )

    end = time.time()

    print("\n===================================")
    print(f"SUCCESS: {success}")
    print(f"TIME TAKEN: {end - start:.2f} sec")
    print("===================================")
