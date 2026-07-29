import type { ReactNode } from 'react';
import { CompanyWorkspace } from '@/components/company/CompanyWorkspace';

export default function CompetitorLayout({ children }: { children: ReactNode }) {
  return <CompanyWorkspace>{children}</CompanyWorkspace>;
}
