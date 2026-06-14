"use client";

import { motion, useReducedMotion, type Variants } from "framer-motion";
import { usePathname } from "next/navigation";
import type { CSSProperties, ReactNode } from "react";

const EASE = [0.2, 0.7, 0.3, 1] as const;

/** Subtle fade+slide on every route change. No-op under prefers-reduced-motion. */
export function PageTransition({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const reduce = useReducedMotion();
  if (reduce) return <>{children}</>;
  return (
    <motion.div
      key={pathname}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.28, ease: EASE }}
    >
      {children}
    </motion.div>
  );
}

/** One-shot reveal when scrolled into view. */
export function Reveal({ children, delay = 0, y = 12, className, style }: {
  children: ReactNode; delay?: number; y?: number; className?: string; style?: CSSProperties;
}) {
  const reduce = useReducedMotion();
  if (reduce) return <div className={className} style={style}>{children}</div>;
  return (
    <motion.div
      className={className}
      style={style}
      initial={{ opacity: 0, y }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-40px" }}
      transition={{ duration: 0.5, delay, ease: EASE }}
    >
      {children}
    </motion.div>
  );
}

const stagger: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.06 } },
};
const item: Variants = {
  hidden: { opacity: 0, y: 14 },
  show: { opacity: 1, y: 0, transition: { duration: 0.45, ease: EASE } },
};

/** Stagger container — children should be <Stagger.Item>. */
export function Stagger({ children, className, style }: {
  children: ReactNode; className?: string; style?: CSSProperties;
}) {
  const reduce = useReducedMotion();
  if (reduce) return <div className={className} style={style}>{children}</div>;
  return (
    <motion.div className={className} style={style}
      variants={stagger} initial="hidden" whileInView="show" viewport={{ once: true, margin: "-40px" }}>
      {children}
    </motion.div>
  );
}

export function StaggerItem({ children, className, style }: {
  children: ReactNode; className?: string; style?: CSSProperties;
}) {
  const reduce = useReducedMotion();
  if (reduce) return <div className={className} style={style}>{children}</div>;
  return <motion.div className={className} style={style} variants={item}>{children}</motion.div>;
}
