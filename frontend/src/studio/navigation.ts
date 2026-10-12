/* The screen map.
 *
 * This is the single source of truth for both the rail and the router, so a
 * screen cannot exist in one and not the other, and the transition design is
 * readable as data rather than spread across a switch statement.
 *
 * Paths are relative to the studio basename, so "/assets" is "/studio/assets".
 */
import {
    Activity,
    BookOpen,
    Boxes,
    ClipboardList,
    Coins,
    FlaskConical,
    Flag,
    Landmark,
    Layers,
    PiggyBank,
    Repeat,
    ScrollText,
    ShieldCheck,
    Wallet,
} from 'lucide-react';
import type { ComponentType } from 'react';

export interface StudioScreen {
    /** Route path under the studio basename. */
    path: string;
    label: string;
    icon: ComponentType<{ size?: number | string; className?: string }>;
    /** Shown in the header above the screen title. */
    section: string;
    /** Tabs are route segments, so a tab is a URL and the back button works. */
    tabs?: Array<{ segment: string; label: string }>;
}

export interface StudioGroup {
    id: string;
    /** Rail heading. Null renders the group without one. */
    label: string | null;
    screens: StudioScreen[];
}

const WORKSPACE = 'ワークスペース';
const DATABASE = 'データベース';
const AUTOMATION = 'オートメーション';
const PROTOTYPE = '試作';

export const STUDIO_GROUPS: StudioGroup[] = [
    {
        id: 'workspace',
        label: 'WORKSPACE',
        screens: [
            {
                path: 'ledger',
                label: '家計簿',
                icon: BookOpen,
                section: WORKSPACE,
                tabs: [
                    { segment: '', label: 'すべての記録' },
                    { segment: 'unmatched', label: '未照合' },
                    // The budget screen owns the plan; repeating numbers at two depths makes them drift apart.
                ],
            },
            {
                path: 'assets',
                label: '資産',
                icon: Wallet,
                section: WORKSPACE,
                tabs: [
                    { segment: '', label: '全体の状況' },
                    { segment: 'accounts', label: '口座' },
                    { segment: 'earmarks', label: '取り置き' },
                ],
            },
            { path: 'flows', label: '収支', icon: Activity, section: WORKSPACE },
            {
                path: 'budget',
                label: '予算',
                icon: ClipboardList,
                section: WORKSPACE,
                tabs: [
                    { segment: '', label: '予算と実績' },
                    { segment: 'actions', label: '行動' },
                ],
            },
            { path: 'goals', label: 'ゴール', icon: Flag, section: WORKSPACE },
        ],
    },
    {
        id: 'database',
        label: 'DATABASE',
        screens: [
            { path: 'db/accounts', label: '口座・勘定科目', icon: Landmark, section: DATABASE },
            { path: 'db/fx', label: '為替レート', icon: Coins, section: DATABASE },
            {
                path: 'db/definitions',
                label: '収支・配分の定義',
                icon: Repeat,
                section: DATABASE,
                tabs: [
                    { segment: '', label: 'サービス・継続支出' },
                    { segment: 'income', label: '収入' },
                    { segment: 'repayment', label: '返済' },
                    { segment: 'allocation', label: '配分' },
                ],
            },
            { path: 'db/fixed-assets', label: '固定資産', icon: Boxes, section: DATABASE },
            { path: 'db/consumables', label: '消耗品', icon: Layers, section: DATABASE },
        ],
    },
    {
        id: 'automation',
        label: 'Automation',
        screens: [
            { path: 'automation/ai', label: 'AI操作', icon: PiggyBank, section: AUTOMATION },
            { path: 'automation/approvals', label: '承認リクエスト', icon: ShieldCheck, section: AUTOMATION },
            { path: 'automation/audit', label: '監査ログ', icon: ScrollText, section: AUTOMATION },
        ],
    },
    {
        id: 'prototype',
        label: 'PROTOTYPE',
        screens: [
            {
                /* Debug surface for data_health. It is deliberately not part of the
                 * product: the decision was to show health as notifications and
                 * inline repair prompts, and to delete this page before release. */
                path: 'debug/data-health',
                label: 'データ健全性',
                icon: FlaskConical,
                section: PROTOTYPE,
            },
        ],
    },
];

export const STUDIO_SCREENS: StudioScreen[] = STUDIO_GROUPS.flatMap((group) => group.screens);

/** Where the rail sends you when nothing is selected. */
export const STUDIO_HOME = 'assets';

export const SETTINGS_PATH = 'settings';
