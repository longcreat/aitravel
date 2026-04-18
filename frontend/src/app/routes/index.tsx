import { createBrowserRouter } from "react-router-dom";
import AuthPage from "@/pages/auth";
import ChatPage from "@/pages/chat";
import ProfilePage from "@/pages/profile";
import { RequireAuthRoute } from "@/features/auth/ui/require-auth-route";
import { LocationPermissionPage } from "@/features/profile/ui/location-permission-page";
import { ProfilePermissionsPage } from "@/features/profile/ui/profile-permissions-page";
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
        path: "chat/:threadId",
        element: <ChatPage />,
      },
      {
        element: <RequireAuthRoute />,
        children: [
          {
            path: "profile",
            element: <ProfilePage />,
          },
          {
            path: "profile/permissions",
            element: <ProfilePermissionsPage />,
          },
          {
            path: "profile/permissions/location",
            element: <LocationPermissionPage />,
          },
        ],
      },
    ],
  },
]);
