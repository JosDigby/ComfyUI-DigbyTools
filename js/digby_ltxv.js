import { app } from "../../scripts/app.js";

app.registerExtension({ 
	name: "DigbyLTXVLatentPrep",
    async setup() {
    },
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name === "DigbyLTXVLatentPrep") {
       		const onConnectionsChange = nodeType.prototype.onConnectionsChange;
    		nodeType.prototype.onConnectionsChange = function (side,slot,connect,link_info,slot_info) {     
	    		const r = onConnectionsChange?.apply(this, arguments);   

                if ((side == 1) && (slot_info.name === "template_images")) {
                    var is_disabled = ((link_info != null) && (connect)) 

                    this.widgets.find(w => w.name === "length_in_seconds").disabled = is_disabled
                    this.widgets.find(w => w.name === "height").disabled = is_disabled
                    this.widgets.find(w => w.name === "width").disabled = is_disabled
                }
               
                return r;
            }
        }
    }
})
    