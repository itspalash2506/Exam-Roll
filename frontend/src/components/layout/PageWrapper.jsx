import { useLocation, useOutlet } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import Navbar from './Navbar.jsx'
import Sidebar from './Sidebar.jsx'
import { pageTransition, useReducedMotion } from '../../lib/motion.js'

export default function PageWrapper() {
  const { pathname } = useLocation()
  const outlet = useOutlet()
  const reduced = useReducedMotion()

  return (
    <div className="flex h-screen flex-col bg-canvas">
      <Navbar />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar />
        <main className="flex-1 overflow-y-auto p-6 lg:p-8">
          <div className="mx-auto w-full max-w-content">
            <AnimatePresence mode="wait" initial={false}>
              <motion.div key={pathname} {...pageTransition(reduced)}>
                {outlet}
              </motion.div>
            </AnimatePresence>
          </div>
        </main>
      </div>
    </div>
  )
}
