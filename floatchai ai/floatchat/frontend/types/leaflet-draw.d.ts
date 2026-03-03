declare module "leaflet-draw";

declare module "react-leaflet-draw" {
  import * as React from "react";

  interface EditControlProps {
    position?: "topleft" | "topright" | "bottomleft" | "bottomright";
    onCreated?: (event: any) => void;
    onEdited?: (event: any) => void;
    onDeleted?: (event: any) => void;
    draw?: Record<string, unknown>;
    edit?: Record<string, unknown>;
  }

  export class EditControl extends React.Component<EditControlProps> {}
}
