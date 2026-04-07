import { useState } from 'react';
import { NavLink } from 'react-router-dom';
import { Menu, X } from 'lucide-react';

interface NavItem {
  to: string;
  label: string;
  end?: boolean;
}

interface ResponsiveNavProps {
  items: NavItem[];
}

export function ResponsiveNav({ items }: ResponsiveNavProps) {
  const [open, setOpen] = useState(false);

  return (
    <nav className="relative">
      {/* Desktop nav — horizontal, full */}
      <div className="hidden md:flex items-center gap-1">
        {items.map(item => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              `nav-link${isActive ? ' active' : ''}`
            }
          >
            {item.label}
          </NavLink>
        ))}
      </div>

      {/* Mobile hamburger */}
      <button
        className="md:hidden flex items-center gap-2 px-3 py-2 text-text-secondary hover:text-text-primary transition-colors"
        onClick={() => setOpen(o => !o)}
        aria-label={open ? 'Close menu' : 'Open menu'}
        aria-expanded={open}
      >
        {open ? <X size={20} /> : <Menu size={20} />}
        <span className="text-sm font-medium">Menu</span>
      </button>

      {/* Mobile dropdown */}
      {open && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-40 bg-bg-primary/60"
            onClick={() => setOpen(false)}
            aria-hidden="true"
          />

          {/* Menu panel */}
          <div className="absolute right-0 top-full mt-2 z-50 w-56 bg-bg-secondary border border-border-color rounded-xl shadow-2xl overflow-hidden">
            <div className="flex flex-col py-2">
              {items.map(item => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  onClick={() => setOpen(false)}
                  className={({ isActive }) =>
                    `px-4 py-3 text-sm font-medium transition-colors ${
                      isActive
                        ? 'bg-accent text-white'
                        : 'text-text-secondary hover:bg-bg-tertiary hover:text-text-primary'
                    }`
                  }
                >
                  {item.label}
                </NavLink>
              ))}
            </div>
          </div>
        </>
      )}
    </nav>
  );
}
