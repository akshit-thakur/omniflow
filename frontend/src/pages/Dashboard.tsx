/**
 * Dashboard Page - Grid of module cards matching original design
 */

import { Link } from 'react-router-dom'
import { Icon, type IconName } from '../components/Icon'

export function DashboardPage() {
    const modules: { path: string; icon: IconName; title: string }[] = [
        { path: '/tasks', icon: 'tasks', title: 'To-Do List' },
        { path: '/medicine', icon: 'medicine', title: 'Medicine Tracker' },
        { path: '/gym', icon: 'gym', title: 'Gym Training' },
        { path: '/cookbook', icon: 'cookbook', title: 'Cookbook' },
        { path: '/inventory', icon: 'inventory', title: 'Kitchen Inventory' },
        { path: '/meals', icon: 'meals', title: 'Meal Planner' },
        { path: '/media', icon: 'media', title: 'Media Tracker' },
        { path: '/database-map', icon: 'database', title: 'Database Map' },
        { path: '/backups', icon: 'download', title: 'Backups' },
    ]

    return (
        <div className="page dashboard">
            <div className="dashboard-cards">
                {modules.map(mod => (
                    <Link key={mod.path} to={mod.path} className="module-card" tabIndex={0}>
                        <span className="module-icon"><Icon name={mod.icon} size={40} /></span>
                        <span className="module-title">{mod.title}</span>
                    </Link>
                ))}
            </div>
        </div>
    )
}
