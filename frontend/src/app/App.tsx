import { RouterProvider } from "react-router-dom";
import { router } from "@/app/routes";
import { Toaster } from "@/shared/ui";

export function App() {
  return (
    <>
      <RouterProvider router={router} />
      <Toaster />
    </>
  );
}
