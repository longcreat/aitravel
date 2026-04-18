import { createBrowserRouter } from "react-router-dom";
import AuthPage from "@/pages/auth";
import ChatPage from "@/pages/chat";
import ProfilePage from "@/pages/profile";
import { RequireAuthRoute } from "@/features/auth/ui/require-auth-route";
import { TabLayout } from "@/shared/layouts/tab-layout";

export const router = createBrowserRouter([
  {
    path: "/auth",
    element: <AuthPage />,
  },
  {
    path: "/",
    element: <TabLayout />,
    children: [
      {
        index: true,
        element: <ChatPage />,
      },
      {
        path: "chat",
        element: <ChatPage />,
      },
      {
        element: <RequireAuthRoute />,
        children: [
          {
            path: "profile",
            element: <ProfilePage />,
          },
        ],
      },
    ],
  },
]);
