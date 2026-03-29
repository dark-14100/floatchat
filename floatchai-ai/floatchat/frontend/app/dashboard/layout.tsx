import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";

export default function DashboardLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return <>{children}</>;
}
