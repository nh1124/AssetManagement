/** The shape of an entry, as a hint for the account pickers.
 *
 *  This is a UI affordance, not a ledger field: nothing here is sent or
 *  stored. The ledger keeps the legs, and the accounts on them already say
 *  what happened. Each shape stands for one pair of account types, so picking
 *  one narrows From and To to the accounts that can sensibly appear there.
 */
export type EntryShape = 'expense' | 'income' | 'transfer' | 'borrowing' | 'debt_payment';

export const ENTRY_SHAPES: Array<{
    value: EntryShape;
    label: string;
    description: string;
    fromTypes: string[];
    toTypes: string[];
}> = [
    {
        value: 'expense',
        label: 'Expense',
        description: 'Spend from cash, a card, or straight out of income. Dr expense, Cr the funding account.',
        fromTypes: ['asset', 'item', 'liability', 'income'],
        toTypes: ['expense', 'item'],
    },
    {
        value: 'income',
        label: 'Income',
        description: 'Receive income into cash or bank. Dr asset, Cr income.',
        fromTypes: ['income'],
        toTypes: ['asset', 'item'],
    },
    {
        value: 'borrowing',
        label: 'Borrowing',
        description: 'Borrow, or buy on credit: a liability funds an asset or an item.',
        fromTypes: ['liability'],
        toTypes: ['asset', 'item'],
    },
    {
        value: 'debt_payment',
        label: 'Debt repayment',
        description: 'Repay debt from cash or bank. Dr liability, Cr asset.',
        fromTypes: ['asset', 'item'],
        toTypes: ['liability'],
    },
    {
        value: 'transfer',
        label: 'Transfer',
        description: 'Move value between accounts you already hold.',
        fromTypes: ['asset', 'item', 'liability', 'income'],
        toTypes: ['asset', 'item', 'liability', 'income'],
    },
];

export const SHAPE_RULES = Object.fromEntries(
    ENTRY_SHAPES.map(({ value, fromTypes, toTypes }) => [value, { fromTypes, toTypes }])
) as Record<EntryShape, { fromTypes: string[]; toTypes: string[] }>;

export const shapeDescription = (shape: EntryShape): string =>
    ENTRY_SHAPES.find((option) => option.value === shape)?.description ?? '';

/** Which shape fits an entry that already has its accounts, for reopening one
 *  in a form. Transfer sits last in ENTRY_SHAPES, so a narrower pair wins. */
export const entryShapeForAccounts = (
    accounts: Array<{ id: number; account_type: string }>,
    fromAccountId?: number | null,
    toAccountId?: number | null,
): EntryShape => {
    const from = accounts.find((account) => account.id === fromAccountId)?.account_type;
    const to = accounts.find((account) => account.id === toAccountId)?.account_type;
    if (!from || !to) return 'expense';
    const match = ENTRY_SHAPES.find(
        (shape) => shape.fromTypes.includes(from) && shape.toTypes.includes(to)
    );
    return match?.value ?? 'transfer';
};
