# Setting up Pandora on another computer

These steps install Pandora on a new Windows computer and, if you want, copy the store data from an existing one. Run commands in **PowerShell**.

> **Backups don't move.** The daily `.dpapi` backups are encrypted with the Windows account that made them and can't be opened on another computer. To move data, use a SQL export (step 4A).

## 1. Install the software

- **Python 3.14**: during install, tick *Add python.exe to PATH*.
- **MySQL Server 8.4**: write down the `root` password you choose.
- **Git**

## 2. Get the code

```powershell
git clone https://github.com/Kenzo-gg/Pandora.git
cd Pandora
python -m venv .venv
.\.venv\Scripts\pip install -r projectsite\requirements.txt
```

Copy `projectsite\.env.example` to `projectsite\.env` and enter this computer's MySQL password after `PANDORA_DB_PASSWORD=`. The `.env` file is ignored by git, so the password stays on this computer.

## 3. Create the database

```powershell
& "C:\Program Files\MySQL\MySQL Server 8.4\bin\mysql.exe" -u root -p -e "CREATE DATABASE pandoradb CHARACTER SET utf8mb4"
```

## 4. Add data: choose A or B

### A. Copy data from an existing computer

On the **old** computer, from the `projectsite` folder:

```powershell
& "C:\Program Files\MySQL\MySQL Server 8.4\bin\mysqldump.exe" -u root -p --single-transaction --no-tablespaces pandoradb --result-file=pandora-export.sql
```

Copy `pandora-export.sql` to the new computer (for example on a USB drive), then on the **new** computer:

```powershell
Get-Content pandora-export.sql -Raw | & "C:\Program Files\MySQL\MySQL Server 8.4\bin\mysql.exe" -u root -p pandoradb
```

This brings over products, suppliers, purchases, sales, expenses, user accounts and their roles. People sign in with the same usernames and passwords as before.

> The export contains password hashes and all store data. Keep it private, never commit it to GitHub, and delete copies (including on the USB drive) once you've imported it.

### B. Start with an empty store

```powershell
cd projectsite
..\.venv\Scripts\python manage.py migrate
..\.venv\Scripts\python manage.py configure_pandora_roles
..\.venv\Scripts\python manage.py createsuperuser
..\.venv\Scripts\python manage.py create_demo_accounts
```

`create_demo_accounts` creates `admin_demo`, `inventory_demo` and `cashier_demo`, and asks you to type a password for each.

## 5. Check it works

```powershell
cd projectsite
..\.venv\Scripts\python manage.py check
..\.venv\Scripts\python manage.py runserver
```

Open http://127.0.0.1:8000 and sign in.

## 6. Set up daily backups (optional)

The scheduled backup task doesn't come with the code. Create it on the new computer, replacing `C:\path\to\Pandora` with where you cloned the repository:

```powershell
schtasks /Create /TN "Pandora Daily Database Backup" /SC DAILY /ST 02:00 /TR "\"C:\path\to\Pandora\.venv\Scripts\python.exe\" -B \"C:\path\to\Pandora\projectsite\manage.py\" backup_pandora"
```

Backups are saved in `%LOCALAPPDATA%\Pandora\Backups`, and the last seven days are kept. To make one now and check that it restores correctly:

```powershell
cd projectsite
..\.venv\Scripts\python -B manage.py backup_pandora --verify-restore
```

## 7. Restore from a backup

Restoring replaces **all** current data with the backup, so stop the Pandora server first. It only works on the computer and Windows account that made the backup.

See which backups you have (newest first):

```powershell
cd projectsite
..\.venv\Scripts\python -B manage.py restore_pandora
```

Restore one by date, by file name, or `latest`. You'll be asked to type the database name to confirm:

```powershell
..\.venv\Scripts\python -B manage.py restore_pandora latest
```

What happens:

1. The backup is loaded into a temporary database and checked table by table. If it's damaged, nothing changes.
2. The current data is saved as `pre-restore-<date>-<time>.dpapi` in the same folder. These files are never deleted automatically.
3. The live database is replaced and every table is checked against the backup. If anything goes wrong, the saved data is put back automatically.

To undo a restore, restore the `pre-restore-…` file it made. If the backup came from an older version of Pandora, run `manage.py migrate` afterwards.
