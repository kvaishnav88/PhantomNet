from app.llm import get_provider
from app.sqlmock import Psql

ps = Psql(get_provider())
queries = [
    "\\dt",
    "\\d payroll",
    "SELECT id, full_name, title, salary FROM employees ORDER BY salary DESC LIMIT 5;",
    "SELECT department, count(*), avg(salary) FROM employees GROUP BY department;",
    "SELECT e.full_name, p.period, p.gross, p.tax, p.net FROM employees e JOIN payroll p ON p.employee_id = e.id WHERE e.id = 3;",
    "SELECT version();",
    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';",
    "DROP TABLE payroll;",
    "SELEC * FROM employees;",
    "SELECT * FROM salaries;",
]
for q in queries:
    out, _ = ps.run(q)
    print(f"hfs_prod=> {q}\n{out}", end="")