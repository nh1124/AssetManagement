import sys
import os
sys.path.append(os.getcwd())

from app.database import SessionLocal, engine
from app import models
from sqlalchemy import func, text

def deduplicate():
    db = SessionLocal()
    try:
        # Find duplicates
        duplicates = db.query(
            models.Account.client_id,
            models.Account.name,
            func.count(models.Account.id)
        ).group_by(
            models.Account.client_id,
            models.Account.name
        ).having(
            func.count(models.Account.id) > 1
        ).all()

        print(f"Found {len(duplicates)} duplicate groups.")

        for client_id, name, count in duplicates:
            print(f"Processing '{name}' for client {client_id} ({count} copies)...")
            
            # Get all accounts for this group, ordered by ID (keep oldest)
            accounts = db.query(models.Account).filter(
                models.Account.client_id == client_id,
                models.Account.name == name
            ).order_by(models.Account.id).all()
            
            keep_account = accounts[0]
            remove_accounts = accounts[1:]
            
            print(f"  Keeping ID: {keep_account.id}")
            
            for acc in remove_accounts:
                print(f"  Merging ID {acc.id} into {keep_account.id}...")
                
                try:
                    # 1. Reassign Journal Entries
                    je_count = db.query(models.JournalEntry).filter(models.JournalEntry.account_id == acc.id).update(
                        {models.JournalEntry.account_id: keep_account.id}
                    )
                    if je_count: print(f"    - Moved {je_count} journal entries")

                    # 2. Reassign Monthly Plan Lines
                    mpl_count = db.query(models.MonthlyPlanLine).filter(models.MonthlyPlanLine.account_id == acc.id).update(
                        {models.MonthlyPlanLine.account_id: keep_account.id}
                    )
                    if mpl_count: print(f"    - Moved {mpl_count} monthly plan lines")
                    
                    # 3. Reassign GoalAllocations
                    alloc_count = db.query(models.GoalAllocation).filter(models.GoalAllocation.account_id == acc.id).update(
                        {models.GoalAllocation.account_id: keep_account.id}
                    )
                    if alloc_count: print(f"    - Moved {alloc_count} allocations")

                    # 4. Reassign Recurring Transactions (From Account)
                    rt_from_count = db.query(models.RecurringTransaction).filter(models.RecurringTransaction.from_account_id == acc.id).update(
                        {models.RecurringTransaction.from_account_id: keep_account.id}
                    )
                    if rt_from_count: print(f"    - Moved {rt_from_count} recurring transactions (from)")

                    # 5. Reassign Recurring Transactions (To Account)
                    rt_to_count = db.query(models.RecurringTransaction).filter(models.RecurringTransaction.to_account_id == acc.id).update(
                        {models.RecurringTransaction.to_account_id: keep_account.id}
                    )
                    if rt_to_count: print(f"    - Moved {rt_to_count} recurring transactions (to)")

                    # 6. Reassign Liabilities
                    liab_count = db.query(models.Liability).filter(models.Liability.account_id == acc.id).update(
                        {models.Liability.account_id: keep_account.id}
                    )
                    if liab_count: print(f"    - Moved {liab_count} liabilities")

                    # Finally, delete the account
                    print(f"    - Deleting account {acc.id}...")
                    db.delete(acc)
                    db.flush() # Force check constraints
                except Exception as ex:
                    print(f"    ! Error processing account {acc.id}: {ex}")
                    db.rollback() 
                
            db.commit()
            print("  Done.")
            
    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    deduplicate()
