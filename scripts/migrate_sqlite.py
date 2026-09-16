"""Copy an idle SQLite deployment into an empty Postgres database atomically.
Source is read-only; repeat against a nonempty target is refused.
Run from services/api with TARGET_DATABASE_URL configured privately.
"""
import os
import sys
from pathlib import Path
from sqlalchemy import create_engine, inspect, select, text
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services/api'))
from desktop_service.db import Base

def migrate(source_path,target_url):
    source=create_engine('sqlite:///'+str(Path(source_path).resolve()))
    target=create_engine(target_url)
    if target.dialect.name!='postgresql':raise ValueError('Target must be Postgres')
    Base.metadata.create_all(target)
    source_tables=set(inspect(source).get_table_names())
    counts={}
    with source.connect() as src,target.begin() as dst:
        for table in Base.metadata.sorted_tables:
            if dst.execute(select(table).limit(1)).first():raise ValueError('Target is not empty; migration refused')
        if 'computers' in source_tables:
            active=src.execute(text("SELECT COUNT(*) FROM computers WHERE status NOT IN ('stopped','deleted','failed')")).scalar()
            if active:raise ValueError('Stop desktops and API/worker before migrating')
        for table in Base.metadata.sorted_tables:
            if table.name not in source_tables:continue
            rows=[dict(row) for row in src.execute(select(table)).mappings()]
            if rows:dst.execute(table.insert(),rows)
            counts[table.name]=len(rows)
            for column in table.primary_key:
                if column.type.python_type is int:
                    sequence=dst.execute(text('SELECT pg_get_serial_sequence(:table,:column)'),{'table':table.name,'column':column.name}).scalar()
                    if sequence:
                        maximum=max((row[column.name] for row in rows),default=0)
                        dst.execute(text('SELECT setval(CAST(:sequence AS regclass), :value, :called)'),{'sequence':sequence,'value':maximum or 1,'called':maximum>0})
    source.dispose();target.dispose()
    return counts

if __name__=='__main__':
    print(migrate(sys.argv[1] if len(sys.argv)>1 else '.local/desktop.db',os.environ['TARGET_DATABASE_URL']))
