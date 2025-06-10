#!/usr/bin/env python3
"""
SQLite MCP Server using FastMCP
A comprehensive MCP server for SQLite database operations with built-in prompts and resources.
"""

import asyncio
import sqlite3
import json
import os
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
from datetime import datetime
import logging

from fastmcp import FastMCP
from pydantic import BaseModel, Field

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Pydantic models for type safety
class QueryParams(BaseModel):
    query: str = Field(description="SQL query to execute")
    params: Optional[List[Any]] = Field(default=None, description="Query parameters")
    database: Optional[str] = Field(default="main.db", description="Database file name")

class SchemaParams(BaseModel):
    database: Optional[str] = Field(default="main.db", description="Database file name")
    table_name: Optional[str] = Field(default=None, description="Specific table name")

class BackupParams(BaseModel):
    source_db: str = Field(description="Source database file")
    backup_path: Optional[str] = Field(default=None, description="Backup file path")

class CreateTableParams(BaseModel):
    database: str = Field(default="main.db", description="Database file name")
    table_name: str = Field(description="Name of the table to create")
    columns: Dict[str, str] = Field(description="Column definitions (name: type)")
    primary_key: Optional[str] = Field(default=None, description="Primary key column")

class SQLiteServerConfig:
    """Configuration for SQLite MCP Server"""
    def __init__(self):
        self.data_dir = Path("./data")
        self.data_dir.mkdir(exist_ok=True)
        self.max_results = 1000
        self.allowed_operations = ["SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER"]

# Initialize server
server = FastMCP("SQLite-MCP-Server", version="1.0.0")
config = SQLiteServerConfig()

# Server prompts - built-in guidance for AI assistants
SERVER_PROMPTS = [
    {
        "name": "sqlite_query_assistant",
        "description": "Help users write efficient SQLite queries",
        "arguments": [
            {
                "name": "task_description",
                "description": "What the user wants to accomplish with the database",
                "required": True
            },
            {
                "name": "table_info",
                "description": "Information about available tables and columns",
                "required": False
            }
        ]
    },
    {
        "name": "database_design_helper",
        "description": "Assist with database schema design and optimization",
        "arguments": [
            {
                "name": "requirements",
                "description": "Business requirements for the database",
                "required": True
            },
            {
                "name": "existing_schema",
                "description": "Current database schema if any",
                "required": False
            }
        ]
    }
]

# Server resources - documentation and examples
SERVER_RESOURCES = [
    {
        "uri": "sqlite://docs/quick-reference",
        "name": "SQLite Quick Reference",
        "description": "Common SQLite commands and syntax",
        "mimeType": "text/markdown"
    },
    {
        "uri": "sqlite://examples/common-queries",
        "name": "Common Query Examples", 
        "description": "Frequently used SQL query patterns",
        "mimeType": "text/markdown"
    },
    {
        "uri": "sqlite://docs/best-practices",
        "name": "SQLite Best Practices",
        "description": "Performance tips and best practices",
        "mimeType": "text/markdown"
    }
]

def get_db_path(database: str) -> Path:
    """Get the full path for a database file"""
    return config.data_dir / database

def execute_query(database: str, query: str, params: Optional[List[Any]] = None) -> Dict[str, Any]:
    """Execute a SQL query and return results"""
    db_path = get_db_path(database)
    
    try:
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            
            # Determine if this is a SELECT query
            query_type = query.strip().upper().split()[0]
            
            if query_type == "SELECT":
                rows = cursor.fetchall()
                # Convert to list of dicts for JSON serialization
                results = [dict(row) for row in rows]
                return {
                    "success": True,
                    "data": results[:config.max_results],
                    "row_count": len(results),
                    "truncated": len(results) > config.max_results
                }
            else:
                conn.commit()
                return {
                    "success": True,
                    "message": f"Query executed successfully. Rows affected: {cursor.rowcount}",
                    "rows_affected": cursor.rowcount
                }
                
    except sqlite3.Error as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }

# MCP Tools Implementation

@server.tool()
async def execute_sql(params: QueryParams) -> Dict[str, Any]:
    """
    Execute a SQL query on the specified SQLite database.
    
    Supports SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, and ALTER operations.
    Use parameters for safe query execution to prevent SQL injection.
    """
    logger.info(f"Executing SQL query on {params.database}: {params.query[:100]}...")
    
    # Basic security check
    query_type = params.query.strip().upper().split()[0]
    if query_type not in config.allowed_operations:
        return {
            "success": False,
            "error": f"Operation {query_type} not allowed"
        }
    
    result = execute_query(params.database, params.query, params.params)
    
    # Add execution metadata
    result["database"] = params.database
    result["timestamp"] = datetime.now().isoformat()
    
    return result

@server.tool()
async def get_schema(params: SchemaParams) -> Dict[str, Any]:
    """
    Get database schema information including tables, columns, and indexes.
    """
    logger.info(f"Getting schema for database: {params.database}")
    
    db_path = get_db_path(params.database)
    
    if not db_path.exists():
        return {
            "success": False,
            "error": f"Database {params.database} does not exist"
        }
    
    try:
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            schema_info = {"success": True, "database": params.database, "tables": {}}
            
            # Get all tables
            if params.table_name:
                table_query = "SELECT name FROM sqlite_master WHERE type='table' AND name=?"
                cursor.execute(table_query, (params.table_name,))
            else:
                table_query = "SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence'"
                cursor.execute(table_query)
            
            tables = [row[0] for row in cursor.fetchall()]
            
            # Get detailed info for each table
            for table in tables:
                # Get columns
                cursor.execute(f"PRAGMA table_info({table})")
                columns = []
                for col in cursor.fetchall():
                    columns.append({
                        "name": col[1],
                        "type": col[2],
                        "not_null": bool(col[3]),
                        "default_value": col[4],
                        "primary_key": bool(col[5])
                    })
                
                # Get indexes
                cursor.execute(f"PRAGMA index_list({table})")
                indexes = []
                for idx in cursor.fetchall():
                    cursor.execute(f"PRAGMA index_info({idx[1]})")
                    index_columns = [col[2] for col in cursor.fetchall()]
                    indexes.append({
                        "name": idx[1],
                        "unique": bool(idx[2]),
                        "columns": index_columns
                    })
                
                # Get row count
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                row_count = cursor.fetchone()[0]
                
                schema_info["tables"][table] = {
                    "columns": columns,
                    "indexes": indexes,
                    "row_count": row_count
                }
            
            return schema_info
            
    except sqlite3.Error as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }

@server.tool()
async def create_table(params: CreateTableParams) -> Dict[str, Any]:
    """
    Create a new table with specified columns and constraints.
    """
    logger.info(f"Creating table {params.table_name} in {params.database}")
    
    # Build CREATE TABLE statement
    column_defs = []
    for col_name, col_type in params.columns.items():
        col_def = f"{col_name} {col_type}"
        if params.primary_key and col_name == params.primary_key:
            col_def += " PRIMARY KEY"
        column_defs.append(col_def)
    
    create_query = f"CREATE TABLE IF NOT EXISTS {params.table_name} ({', '.join(column_defs)})"
    
    return execute_query(params.database, create_query)

@server.tool()
async def backup_database(params: BackupParams) -> Dict[str, Any]:
    """
    Create a backup copy of a SQLite database.
    """
    logger.info(f"Backing up database: {params.source_db}")
    
    source_path = get_db_path(params.source_db)
    
    if not source_path.exists():
        return {
            "success": False,
            "error": f"Source database {params.source_db} does not exist"
        }
    
    # Generate backup filename if not provided
    if not params.backup_path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{source_path.stem}_backup_{timestamp}.db"
        backup_path = config.data_dir / backup_name
    else:
        backup_path = Path(params.backup_path)
    
    try:
        # Use SQLite backup API for consistent backup
        source_conn = sqlite3.connect(str(source_path))
        backup_conn = sqlite3.connect(str(backup_path))
        
        source_conn.backup(backup_conn)
        
        source_conn.close()
        backup_conn.close()
        
        return {
            "success": True,
            "message": f"Database backed up successfully",
            "backup_path": str(backup_path),
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }

@server.tool()
async def list_databases() -> Dict[str, Any]:
    """
    List all available SQLite databases in the data directory.
    """
    logger.info("Listing available databases")
    
    try:
        databases = []
        for db_file in config.data_dir.glob("*.db"):
            stat = db_file.stat()
            databases.append({
                "name": db_file.name,
                "size_bytes": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "path": str(db_file)
            })
        
        return {
            "success": True,
            "databases": databases,
            "count": len(databases)
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

@server.tool()
async def optimize_database(database: str) -> Dict[str, Any]:
    """
    Optimize database by running VACUUM and ANALYZE commands.
    """
    logger.info(f"Optimizing database: {database}")
    
    results = []
    
    # Run VACUUM
    vacuum_result = execute_query(database, "VACUUM")
    results.append({"operation": "VACUUM", "result": vacuum_result})
    
    # Run ANALYZE
    analyze_result = execute_query(database, "ANALYZE")
    results.append({"operation": "ANALYZE", "result": analyze_result})
    
    return {
        "success": True,
        "message": "Database optimization completed",
        "operations": results,
        "timestamp": datetime.now().isoformat()
    }

# MCP Prompts Implementation

@server.prompt("sqlite_query_assistant")
async def sqlite_query_assistant(task_description: str, table_info: str = "") -> str:
    """Generate helpful guidance for writing SQLite queries"""
    
    base_prompt = f"""
# SQLite Query Assistant

## Task: {task_description}

## Available Table Information:
{table_info if table_info else "No table information provided. Use get_schema tool to explore database structure."}

## Query Writing Guidelines:

### Common Patterns:
- **SELECT with filtering**: `SELECT column1, column2 FROM table WHERE condition`
- **Aggregation**: `SELECT COUNT(*), AVG(column) FROM table GROUP BY category`
- **Joins**: `SELECT a.col, b.col FROM table1 a JOIN table2 b ON a.id = b.foreign_id`
- **Subqueries**: `SELECT * FROM table WHERE id IN (SELECT id FROM other_table WHERE condition)`

### SQLite-Specific Features:
- Use `LIMIT` for pagination: `SELECT * FROM table LIMIT 10 OFFSET 20`
- Date functions: `date('now')`, `datetime('now', '-1 day')`
- JSON support: `json_extract(column, '$.field')`
- Full-text search: Create FTS table for text search capabilities

### Performance Tips:
- Always use indexes for WHERE clauses on large tables
- Use EXPLAIN QUERY PLAN to analyze query performance
- Consider using views for complex recurring queries
- Use parameters (?) for dynamic values to prevent SQL injection

### Safety Reminders:
- Always use parameterized queries for user input
- Test queries on small datasets first
- Use transactions for multiple related operations
- Regular backups before major data modifications
"""
    
    return base_prompt

@server.prompt("database_design_helper")
async def database_design_helper(requirements: str, existing_schema: str = "") -> str:
    """Provide guidance on database schema design"""
    
    design_prompt = f"""
# Database Design Helper

## Requirements: {requirements}

## Current Schema:
{existing_schema if existing_schema else "Starting with a new database design."}

## Design Principles:

### Normalization Guidelines:
- **1NF**: Each column contains atomic values
- **2NF**: All non-key columns depend on the entire primary key
- **3NF**: No transitive dependencies between non-key columns
- **Consider denormalization** for read-heavy applications

### SQLite-Specific Considerations:
- **Data Types**: INTEGER, TEXT, REAL, BLOB, NUMERIC
- **Primary Keys**: Use INTEGER PRIMARY KEY for auto-incrementing IDs
- **Foreign Keys**: Enable with `PRAGMA foreign_keys = ON`
- **Indexes**: Create indexes for frequently queried columns
- **Size Limits**: SQLite handles databases up to 281TB

### Common Design Patterns:
- **Audit Trails**: Add created_at, updated_at timestamps
- **Soft Deletes**: Use deleted_at column instead of DELETE
- **Versioning**: Maintain version numbers for records
- **Lookup Tables**: Separate tables for categories, statuses

### Schema Evolution:
- Use ALTER TABLE for schema changes
- Create migration scripts for version control
- Always backup before schema modifications
- Test schema changes in development first

### Performance Optimization:
- Index foreign key columns
- Use partial indexes for filtered queries
- Consider covering indexes for read-heavy queries
- Monitor query performance with EXPLAIN QUERY PLAN
"""
    
    return design_prompt

# MCP Resources Implementation

@server.resource("sqlite://docs/quick-reference")
async def sqlite_quick_reference() -> str:
    """SQLite Quick Reference Guide"""
    return """
# SQLite Quick Reference

## Basic Commands

### Database Operations
```sql
-- Create/Open database (automatic)
-- Attach additional database
ATTACH DATABASE 'other.db' AS other_db;

-- List tables
.tables
-- or
SELECT name FROM sqlite_master WHERE type='table';

-- Show schema
.schema table_name
-- or  
PRAGMA table_info(table_name);
```

### Table Operations
```sql
-- Create table
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT UNIQUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Alter table
ALTER TABLE users ADD COLUMN phone TEXT;
ALTER TABLE users RENAME TO customers;

-- Drop table
DROP TABLE IF EXISTS temp_table;
```

### Data Operations
```sql
-- Insert data
INSERT INTO users (name, email) VALUES ('John', 'john@email.com');
INSERT OR REPLACE INTO users (id, name, email) VALUES (1, 'Jane', 'jane@email.com');

-- Update data
UPDATE users SET email = 'newemail@email.com' WHERE id = 1;

-- Delete data
DELETE FROM users WHERE id = 1;

-- Select data
SELECT * FROM users WHERE name LIKE 'J%' ORDER BY created_at DESC LIMIT 10;
```

### Useful Functions
```sql
-- Date/Time
SELECT date('now'), datetime('now', '+1 day');

-- String functions
SELECT upper(name), length(email), substr(name, 1, 3) FROM users;

-- Aggregation
SELECT COUNT(*), AVG(age), MAX(created_at) FROM users;

-- JSON (SQLite 3.45+)
SELECT json_extract(data, '$.field') FROM table_with_json;
```

### Indexes
```sql
-- Create index
CREATE INDEX idx_users_email ON users(email);
CREATE UNIQUE INDEX idx_users_username ON users(username);

-- Partial index
CREATE INDEX idx_active_users ON users(name) WHERE active = 1;

-- Drop index
DROP INDEX idx_users_email;
```

### Pragma Commands
```sql
-- Enable foreign keys
PRAGMA foreign_keys = ON;

-- Check database integrity
PRAGMA integrity_check;

-- Optimize database
VACUUM;
ANALYZE;

-- Show database info
PRAGMA database_list;
PRAGMA table_info(table_name);
```
"""

@server.resource("sqlite://examples/common-queries")
async def common_queries() -> str:
    """Common SQLite Query Examples"""
    return """
# Common SQLite Query Examples

## Data Retrieval

### Basic Filtering
```sql
-- Find users by name pattern
SELECT * FROM users WHERE name LIKE '%john%';

-- Find users created in last 30 days
SELECT * FROM users WHERE created_at >= date('now', '-30 days');

-- Find users with specific email domains
SELECT * FROM users WHERE email LIKE '%@gmail.com';
```

### Aggregation and Grouping
```sql
-- Count users by domain
SELECT 
    substr(email, instr(email, '@') + 1) as domain,
    COUNT(*) as user_count
FROM users 
GROUP BY domain 
ORDER BY user_count DESC;

-- Monthly registration stats
SELECT 
    strftime('%Y-%m', created_at) as month,
    COUNT(*) as registrations
FROM users 
GROUP BY month 
ORDER BY month;

-- Find duplicate emails
SELECT email, COUNT(*) 
FROM users 
GROUP BY email 
HAVING COUNT(*) > 1;
```

### Joins and Relationships
```sql
-- Inner join with order details
SELECT 
    u.name,
    o.order_date,
    o.total_amount
FROM users u
INNER JOIN orders o ON u.id = o.user_id
WHERE o.order_date >= date('now', '-1 month');

-- Left join to find users without orders
SELECT 
    u.name,
    u.email,
    COUNT(o.id) as order_count
FROM users u
LEFT JOIN orders o ON u.id = o.user_id
GROUP BY u.id, u.name, u.email
HAVING order_count = 0;

-- Self join for hierarchical data
SELECT 
    e.name as employee,
    m.name as manager
FROM employees e
LEFT JOIN employees m ON e.manager_id = m.id;
```

## Data Modification

### Bulk Operations
```sql
-- Update multiple records
UPDATE products 
SET price = price * 1.1 
WHERE category = 'electronics';

-- Insert from select
INSERT INTO archived_orders 
SELECT * FROM orders 
WHERE order_date < date('now', '-1 year');

-- Delete with subquery
DELETE FROM users 
WHERE id IN (
    SELECT user_id 
    FROM user_sessions 
    WHERE last_activity < date('now', '-6 months')
);
```

### Conditional Logic
```sql
-- Case statement for categorization
SELECT 
    name,
    CASE 
        WHEN age < 18 THEN 'Minor'
        WHEN age < 65 THEN 'Adult'
        ELSE 'Senior'
    END as age_group
FROM users;

-- Conditional updates
UPDATE orders 
SET status = CASE 
    WHEN total_amount > 1000 THEN 'priority'
    WHEN total_amount > 500 THEN 'standard'
    ELSE 'economy'
END;
```

## Advanced Patterns

### Window Functions
```sql
-- Row numbers and rankings
SELECT 
    name,
    salary,
    ROW_NUMBER() OVER (ORDER BY salary DESC) as rank,
    RANK() OVER (ORDER BY salary DESC) as dense_rank
FROM employees;

-- Running totals
SELECT 
    order_date,
    daily_total,
    SUM(daily_total) OVER (ORDER BY order_date) as running_total
FROM daily_sales;
```

### Common Table Expressions (CTE)
```sql
-- Recursive CTE for hierarchical data
WITH RECURSIVE org_chart AS (
    SELECT id, name, manager_id, 0 as level
    FROM employees 
    WHERE manager_id IS NULL
    
    UNION ALL
    
    SELECT e.id, e.name, e.manager_id, oc.level + 1
    FROM employees e
    JOIN org_chart oc ON e.manager_id = oc.id
)
SELECT * FROM org_chart ORDER BY level, name;
```

### Full-Text Search
```sql
-- Create FTS table
CREATE VIRTUAL TABLE documents_fts USING fts5(title, content);

-- Insert data
INSERT INTO documents_fts SELECT title, content FROM documents;

-- Search
SELECT * FROM documents_fts WHERE documents_fts MATCH 'sqlite database';
```
"""

@server.resource("sqlite://docs/best-practices")
async def best_practices() -> str:
    """SQLite Best Practices Guide"""
    return """
# SQLite Best Practices

## Performance Optimization

### Indexing Strategy
- **Create indexes** for columns frequently used in WHERE clauses
- **Composite indexes** for multi-column searches: `CREATE INDEX idx_name_date ON table(name, date)`
- **Partial indexes** for filtered queries: `CREATE INDEX idx_active ON table(status) WHERE active = 1`
- **Covering indexes** to avoid table lookups: `CREATE INDEX idx_cover ON table(id) INCLUDE (name, email)`

### Query Optimization
```sql
-- Use EXPLAIN QUERY PLAN to analyze performance
EXPLAIN QUERY PLAN SELECT * FROM users WHERE email = ?;

-- Prefer EXISTS over IN for subqueries
SELECT * FROM users WHERE EXISTS (SELECT 1 FROM orders WHERE user_id = users.id);

-- Use LIMIT for large result sets
SELECT * FROM large_table ORDER BY date DESC LIMIT 100;

-- Avoid functions in WHERE clauses
-- Bad: WHERE upper(name) = 'JOHN'
-- Good: WHERE name = 'john' (with proper case handling)
```

### Transaction Management
```sql
-- Use transactions for multiple related operations
BEGIN TRANSACTION;
INSERT INTO orders (user_id, total) VALUES (1, 100.00);
INSERT INTO order_items (order_id, product_id, quantity) VALUES (last_insert_rowid(), 1, 2);
COMMIT;

-- Use WAL mode for better concurrency
PRAGMA journal_mode = WAL;
```

## Data Integrity

### Constraints and Validation
```sql
-- Use CHECK constraints for data validation
CREATE TABLE products (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    price DECIMAL(10,2) CHECK (price > 0),
    category TEXT CHECK (category IN ('electronics', 'clothing', 'books'))
);

-- Enable foreign key constraints
PRAGMA foreign_keys = ON;

-- Use NOT NULL where appropriate
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

### Safe Data Operations
```sql
-- Always use parameterized queries
-- Python example: cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))

-- Test modifications on copies first
CREATE TABLE users_backup AS SELECT * FROM users;

-- Use transactions for data migrations
BEGIN TRANSACTION;
-- migration steps here
-- Verify results before COMMIT
SELECT COUNT(*) FROM table_name; -- verification
COMMIT; -- or ROLLBACK if issues found
```

## Schema Design

### Naming Conventions
- **Tables**: plural nouns (users, orders, products)
- **Columns**: snake_case (first_name, created_at, user_id)
- **Indexes**: descriptive prefixes (idx_users_email, uk_products_sku)
- **Foreign keys**: reference_table_id (user_id, product_id)

### Data Types Best Practices
```sql
-- Use appropriate SQLite types
CREATE TABLE example (
    id INTEGER PRIMARY KEY,           -- Auto-incrementing
    name TEXT NOT NULL,              -- Variable length text
    price REAL,                      -- Floating point
    quantity INTEGER,                -- Whole numbers
    data BLOB,                       -- Binary data
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### Relationship Design
```sql
-- One-to-Many with proper foreign keys
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    order_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Many-to-Many with junction table
CREATE TABLE user_roles (
    user_id INTEGER,
    role_id INTEGER,
    assigned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, role_id),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (role_id) REFERENCES roles(id)
);
```

## Maintenance and Monitoring

### Regular Maintenance
```sql
-- Optimize database regularly
VACUUM;           -- Reclaim space and defragment
ANALYZE;          -- Update statistics for query planner
PRAGMA optimize;  -- SQLite 3.18+ automatic optimization

-- Check database integrity
PRAGMA integrity_check;
PRAGMA foreign_key_check;
```

### Backup Strategies
```sql
-- Simple backup using SQL
.backup backup_file.db

-- Or using SQLite backup API in application code
-- Create incremental backups for large databases
-- Test restore procedures regularly
```

### Monitoring Performance
```sql
-- Enable query statistics
PRAGMA compile_options;  -- Check available features

-- Monitor database size
SELECT 
    page_count * page_size as size_bytes,
    page_count,
    page_size
FROM pragma_page_count(), pragma_page_size();

-- Track slow queries in application logs
-- Set query timeout limits
-- Monitor concurrent connection counts
```

## Security Considerations

### SQL Injection Prevention
- **Always use parameterized queries**
- **Validate input data types and ranges**
- **Use allowlists for dynamic table/column names**
- **Limit database permissions**

### Access Control
```sql
-- Use views to limit data access
CREATE VIEW public_users AS 
SELECT id, name, email FROM users 
WHERE active = 1;

-- Consider row-level security for multi-tenant apps
-- Implement application-level access controls
```

### Data Protection
- **Encrypt sensitive data at application level**
- **Use SQLite encryption extensions for database files**
- **Regular security audits of queries and access patterns**
- **Implement proper logging and monitoring**
"""

# Server startup and configuration
async def main():
    """Main server startup function"""
    logger.info("Starting SQLite MCP Server...")
    
    # Register prompts and resources
    for prompt in SERVER_PROMPTS:
        logger.info(f"Registered prompt: {prompt['name']}")
    
    for resource in SERVER_RESOURCES:
        logger.info(f"Registered resource: {resource['name']}")
    
    # Ensure data directory exists
    config.data_dir.mkdir(exist_ok=True)
    logger.info(f"Data directory: {config.data_dir.absolute()}")
    
    # Start the server
    await server.run()

if __name__ == "__main__":
    asyncio.run(main())