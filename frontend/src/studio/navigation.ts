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
    ChartLine,
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
import type { TranslationKey } from './i18n';

export interface StudioScreen {
    /** Route path under the studio basename. */
    path: string;
    label: TranslationKey;
    icon: ComponentType<{ size?: number | string; className?: string }>;
    /** Shown in the header above the screen title. */
    section: TranslationKey;
    /** Tabs are route segments, so a tab is a URL and the back button works. */
    tabs?: Array<{ segment: string; label: TranslationKey }>;
}

export interface StudioGroup {
    id: string;
    /** Rail heading. Null renders the group without one. */
    label: TranslationKey | null;
    screens: StudioScreen[];
}

const WORKSPACE = 'group.workspace';
const DATABASE = 'group.database';
const AUTOMATION = 'group.automation';
const PROTOTYPE = 'group.prototype';

export const STUDIO_GROUPS: StudioGroup[] = [
    {
        id: 'workspace',
        label: 'group.workspace',
        screens: [
            {
                path: 'ledger',
                label: 'screen.ledger',
                icon: BookOpen,
                section: WORKSPACE,
                tabs: [
                    { segment: '', label: 'tab.records' },
                    { segment: 'unmatched', label: 'tab.unmatched' },
                    // The budget screen owns the plan; repeating numbers at two depths makes them drift apart.
                ],
            },
            {
                path: 'assets',
                label: 'screen.assets',
                icon: Wallet,
                section: WORKSPACE,
                tabs: [
                    { segment: '', label: 'tab.overview' },
                    { segment: 'accounts', label: 'tab.accounts' },
                    { segment: 'earmarks', label: 'tab.earmarks' },
                ],
            },
            {
                path: 'flows', label: 'screen.flows', icon: Activity, section: WORKSPACE,
                tabs: [
                    { segment: '', label: 'tab.categories' },
                    { segment: 'accounts', label: 'tab.subjects' },
                ],
            },
            {
                path: 'budget',
                label: 'screen.budget',
                icon: ClipboardList,
                section: WORKSPACE,
                tabs: [
                    { segment: '', label: 'tab.budget' },
                    { segment: 'actions', label: 'tab.actions' },
                ],
            },
            {
                path: 'report',
                label: 'screen.report',
                icon: ChartLine,
                section: WORKSPACE,
                tabs: [
                    { segment: '', label: 'tab.trends' },
                    { segment: 'monthly', label: 'tab.monthly' },
                    { segment: 'review', label: 'tab.review' },
                ],
            },
            {
                path: 'goals', label: 'screen.goals', icon: Flag, section: WORKSPACE,
                tabs: [
                    { segment: '', label: 'tab.goal' },
                    { segment: 'events', label: 'tab.lifeEvents' },
                    { segment: 'graph', label: 'tab.graph' },
                ],
            },
        ],
    },
    {
        id: 'database',
        label: 'group.database',
        screens: [
            { path: 'db/accounts', label: 'screen.accounts', icon: Landmark, section: DATABASE },
            { path: 'db/fx', label: 'screen.fx', icon: Coins, section: DATABASE },
            {
                path: 'db/definitions',
                label: 'screen.definitions',
                icon: Repeat,
                section: DATABASE,
                tabs: [
                    { segment: '', label: 'tab.services' },
                    { segment: 'income', label: 'tab.income' },
                    { segment: 'repayment', label: 'tab.repayment' },
                    { segment: 'allocation', label: 'tab.allocation' },
                ],
            },
            { path: 'db/fixed-assets', label: 'screen.fixedAssets', icon: Boxes, section: DATABASE },
            { path: 'db/consumables', label: 'screen.consumables', icon: Layers, section: DATABASE },
        ],
    },
    {
        id: 'automation',
        label: 'group.automation',
        screens: [
            { path: 'automation/ai', label: 'screen.ai', icon: PiggyBank, section: AUTOMATION },
            { path: 'automation/approvals', label: 'screen.approvals', icon: ShieldCheck, section: AUTOMATION },
            { path: 'automation/audit', label: 'screen.audit', icon: ScrollText, section: AUTOMATION },
        ],
    },
    {
        id: 'prototype',
        label: 'group.prototype',
        screens: [
            {
                /* Debug surface for data_health. It is deliberately not part of the
                 * product: the decision was to show health as notifications and
                 * inline repair prompts, and to delete this page before release. */
                path: 'debug/data-health',
                label: 'screen.health',
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

// Editor URLs belong to the route map without adding destinations to the rail.
export const STUDIO_EDITOR_PATHS = {
    record: 'record',
    transaction: 'record/:transactionId',
    newGoal: 'goals/events/new',
    editGoal: 'goals/events/:goalId/edit',
} as const;
