/**
 * Icon - the single place the app imports an icon vendor.
 *
 * Pages address icons by semantic name ("delete", "stats"), never by the
 * vendor's name (Trash2, BarChart3), so the underlying set can be swapped
 * here without touching a single page.
 *
 * Outline SVG replaces emoji because emoji render from whatever font the OS
 * supplies, so shape, weight, colour and baseline differ per platform.
 */

import {
    ArrowDown,
    ArrowUp,
    BarChart3,
    BookMarked,
    BookOpen,
    Bot,
    Calendar,
    Carrot,
    Check,
    ChevronDown,
    ChevronUp,
    Clapperboard,
    ClipboardList,
    ClipboardPlus,
    Disc3,
    Dumbbell,
    Database,
    Download,
    FileVideo,
    Gamepad2,
    Headphones,
    Heart,
    Import,
    ListChecks,
    Mic,
    Package,
    Pencil,
    Pill,
    Plus,
    Refrigerator,
    Send,
    Sparkles,
    Star,
    Target,
    TrendingDown,
    TriangleAlert,
    Trash2,
    Tv,
    Upload,
    UtensilsCrossed,
    X,
    type LucideIcon,
} from 'lucide-react'

const REGISTRY = {
    // Module / navigation icons
    tasks: ListChecks,
    medicine: Pill,
    gym: Dumbbell,
    cookbook: BookOpen,
    inventory: Refrigerator,
    meals: UtensilsCrossed,
    media: Clapperboard,
    database: Database,

    // Actions
    delete: Trash2,
    edit: Pencil,
    close: X,
    check: Check,
    send: Send,
    import: Import,
    upload: Upload,
    download: Download,
    add: Plus,

    // Views and status
    stats: BarChart3,
    list: ClipboardList,
    plan: ClipboardPlus,
    calendar: Calendar,
    warning: TriangleAlert,
    lowStock: TrendingDown,
    package: Package,
    star: Star,
    favorite: Heart,
    target: Target,
    bot: Bot,
    carrot: Carrot,

    // Media types (keys match media_items.media_type)
    book: BookMarked,
    movie: Clapperboard,
    tv_show: Tv,
    video_game: Gamepad2,
    podcast: Mic,
    documentary: FileVideo,
    anime: Sparkles,
    manga: BookOpen,
    music_album: Disc3,
    audiobook: Headphones,

    // Disclosure and sort
    up: ChevronUp,
    down: ChevronDown,
    sortAsc: ArrowUp,
    sortDesc: ArrowDown,
} satisfies Record<string, LucideIcon>

export type IconName = keyof typeof REGISTRY

interface IconProps {
    name: IconName
    size?: number
    /**
     * Supply for a standalone icon (an icon-only button); the icon then
     * announces itself. Omit when adjacent text already names the control,
     * so screen readers do not read the label twice.
     */
    label?: string
    className?: string
}

export function Icon({ name, size = 20, label, className }: IconProps) {
    const Glyph = REGISTRY[name]
    return (
        <Glyph
            size={size}
            strokeWidth={1.75}
            className={className}
            aria-hidden={label ? undefined : true}
            aria-label={label}
            role={label ? 'img' : undefined}
            focusable="false"
        />
    )
}

export default Icon
