import { AuthProvider } from "@/features/auth/model/auth.context";
import { RouterProvider } from "react-router-dom";
import { router } from "@/app/routes";
import { Toaster } from "@/shared/ui";

export function App() {
  return (
    <AuthProvider>
      <RouterProvider router={router} />
      <Toaster />
    </AuthProvider>
  );
}
