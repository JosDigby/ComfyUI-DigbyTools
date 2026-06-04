import { app } from "../../scripts/app.js";

app.registerExtension({
    name: "DigbyKeyframer",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name === "DigbyKeyframer") {
            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function() {
                const node = this;
                
                if (onNodeCreated) {
                    onNodeCreated.apply(this, arguments);
                }

                if (!this.size) this.size = [400,500];

                // --- Graph area margins ---
                this.graph_side_margin = 25;
                this.graph_bottom_margin = 20;

                this.keyframe_count = 0;

                // Initialize points before creating widgets
                if (!this.points || !Array.isArray(this.points)) {
                    this.points = []
                }

                // --- Widget for curve data with callback ---
                if (!this.widgets) this.widgets = [];
               
                // Create the keyframe_data widget with callback directly
                if (!this.widgets.find(w => w.name === "keyframe_data")) {
                    const curveDataCallback = (value) => {
                        let loaded = false;
                        if (value) {
                            try {
                                const data = JSON.parse(value);
                                if (data && Array.isArray(data.keyframes) && data.keyframes.length >= 2) {
                                    node.points = data.keyframes.map(pt => ({
                                        x: Number(pt.x)
                                    }));
                                    loaded = true;
                                } else if (data && Array.isArray(data.samples) && data.samples.length >= 2) {
                                    node.points = [
                                        {x: Number(data.samples[0][0])},
                                        {x: Number(data.samples[data.samples.length-1][0])}
                                    ];
                                    loaded = true;
                                }
                            } catch (e) {}
                        }
                        if (!loaded) {
                            node.points = []
                        }
                        node.updateCurve();
                        node.setDirtyCanvas(true, true);
                    };
/*
                    this.addWidget(
                        "string",
                        "keyframe_data",
                        "",
                        curveDataCallback,
                        { multiline: false, disabled: false }
                    );*/
                }

                

                // --- Try to load points from the widget value (JSON) ---
                const widget = this.widgets.find(w => w.name === "keyframe_data");
                if (widget && widget.value) {
                    try {
                        const data = JSON.parse(widget.value);
                        if (data && Array.isArray(data.keyframes) && data.keyframes.length >= 2) {
                            this.points = data.keyframes.map(pt => ({
                                x: Number(pt.x)
                            }));
                        } else if (data && Array.isArray(data.samples) && data.samples.length >= 2) {
                            // Use endpoints as fallback
                            this.points = [
                                {x: Number(data.samples[0][0])},
                                {x: Number(data.samples[data.samples.length-1][0])}
                            ];
                        }
                    } catch (e) {
                        // ignore parse error, will use default points
                    }
                }

                this.dragState = null;
                this.hitRadius = 0.5;

                this._ensureValidPoints();
                this.updateCurve();
                this._updateCurveWidget();

                // --- Override mouse event handling ---
                // Store the original methods
                const originalOnMouseDown = this.onMouseDown;
                const originalOnMouseMove = this.onMouseMove;
                const originalOnMouseUp = this.onMouseUp;

                // Create bound versions of our mouse handlers
                this.onMouseDown = function(e, pos, canvas) {
                    
                    node.calcGraphArea();
                    
                    // Check if click is inside the graph area
                    if (
                        pos[0] >= node.graph_area_left &&
                        pos[0] <= node.graph_area_left + node.graph_area_width &&
                        pos[1] >= node.graph_area_top &&
                        pos[1] <= node.graph_area_top + node.graph_area_height
                    ) {
                        // Click is inside graph area
                        
                        const graphPos = node.toGraphCoords(pos);
                        const pointIndex = node.points.findIndex(p =>
                            Math.abs(p.x - graphPos.x) < node.hitRadius
                        );
                        
                        if (pointIndex >= 0) {
                            if (e.button === 0) {
                                node.dragState = {
                                    index: pointIndex,
                                    offsetX: graphPos.x - node.points[pointIndex].x
                                };
                                app.graph.change();
                                node.setDirtyCanvas(true, true);
                                return true;
                            }
                        }
                        
                        return true; // Prevent default behavior when clicking in graph area
                    }
                    
                    // Call original handler for clicks outside graph area
                    if (originalOnMouseDown) {
                        return originalOnMouseDown.apply(this, arguments);
                    }
                    return false;
                };

                this.onMouseMove = function(e, pos, canvas) {
                    if (node.dragState) {
                        
                        node.calcGraphArea();
                        
                        const graphPos = node.toGraphCoords(pos);
                        let newX = Math.max(0, Math.min(this.getDuration(), graphPos.x - node.dragState.offsetX));
                        const i = node.dragState.index;
                        
                        if (i > 0) newX = Math.max(node.points[i - 1].x + 1e-3, newX);
                        if (i < node.points.length - 1) newX = Math.min(node.points[i + 1].x - 1e-3, newX);
                        
                        node.points[i] = { x: newX };
                        node.updateCurve();
                        node.setDirtyCanvas(true, true);
                        return true;
                    }
                    
                    if (originalOnMouseMove) {
                        return originalOnMouseMove.apply(this, arguments);
                    }
                    return false;
                };

                this.onMouseUp = function(e, pos, canvas) {
                    if (node.dragState) {
                        node.dragState = null;
                        app.graph.change();
                        return true;
                    }
                    
                    if (originalOnMouseUp) {
                        return originalOnMouseUp.apply(this, arguments);
                    }
                    return false;
                };
            };

            // Add all the other methods to the prototype
            Object.assign(nodeType.prototype, {
                calcGraphArea() {
                    // Calculate the exact position where widgets end
                    let widgets_bottom = 10; // Space for node title
                    let bottom_widget_y = 0

                    if (this.widgets && this.widgets.length) {
                        this.widgets.forEach(w => {
                            let widget_height = 30; // Default height
                            
                            if (w.type === "combo") widget_height = 30;
                            else if (w.type === "number") widget_height = 30;
                            else if (w.type === "string" && w.options && w.options.multiline) {
                                widget_height = 80; 
                            }
                            else if (w.type === "string") widget_height = 30;
                            
                            if (bottom_widget_y < w.y) bottom_widget_y = w.y

                            widgets_bottom += widget_height;
                        });
                        
                        widgets_bottom += 10; 

                        widgets_bottom = bottom_widget_y + 10
                    }
                    
                    const extra_clearance = 20;
                    this.graph_area_top = widgets_bottom + extra_clearance;
                    
                    // Calculate available space for graph
                    this.graph_area_height = this.size[1] - this.graph_area_top - this.graph_bottom_margin;
                    this.graph_area_width = this.size[0] - this.graph_side_margin * 2;
                    this.graph_area_left = this.graph_side_margin;
                    
                    // Ensure minimum graph height
                    const min_graph_height = 50;
                    if (this.graph_area_height < min_graph_height) {
                        const additional_height = min_graph_height - this.graph_area_height;
                        this.size[1] += additional_height;
                        this.graph_area_height = min_graph_height;
                        
                        if (this.setSize) {
                            this.setSize(this.size);
                        }
                    }
                },

                _ensureValidPoints() {
                    if (!Array.isArray(this.points)) {
                        this.points = [];
                    }
                    this.points = this.points
                        .map(p => ({
                            x: p.x // replaces Math.max(0, Math.min(1, p.x))
                        }))
                        .sort((a, b) => a.x - b.x);
                    this.points = this.points.filter((pt, idx, arr) =>
                        idx === 0 || pt.x !== arr[idx - 1].x
                    );
                },

                toScreenCoords(point) {
                    this.calcGraphArea();
                    return [
                        this.graph_area_left + (point.x * this.graph_area_width / this.getDuration()),
                        this.graph_area_top + (1 - point.y) * this.graph_area_height
                    ];
                },

                toGraphCoords(pos) {
                    this.calcGraphArea();
                    return {
                        x: this.getDuration() * Math.max(0, Math.min(1, (pos[0] - this.graph_area_left) / this.graph_area_width))
                    };
                },

                getDuration() {
                    const widget = this.widgets.find(w => w.name === "length_in_seconds") 
                    if (widget) 
                        return(widget.value)
                    else 
                        return(1)
                },
                
                onDrawForeground(ctx) {
                    this.calcGraphArea();
                    this._ensureValidPoints();
                    this.updateCurve();

                    // --- White background for the graph area ---
                    ctx.fillStyle = "#222";
                    ctx.fillRect(
                        this.graph_area_left,
                        this.graph_area_top,
                        this.graph_area_width,
                        this.graph_area_height
                    );

                    const duration = this.getDuration()
                    
                    // --- Draw grid ---
                    ctx.strokeStyle = "#444";
                    ctx.lineWidth = 1;
                    for (let i = 0; i <= duration; i += 1) {
                        // Vertical grid lines
                        let x = this.graph_area_left + (i/duration) * this.graph_area_width;
                        ctx.beginPath();
                        if ((i % 5) == 0) {
                            ctx.lineWidth = 2
                            ctx.strokeStyle = "#888"
                        } else {
                            ctx.lineWidth = 1
                            ctx.strokeStyle = "#333"
                        }
                        ctx.moveTo(x, this.graph_area_top);
                        ctx.lineTo(x, this.graph_area_top + this.graph_area_height);
                        ctx.stroke();

                        // Label the lines
                        if (i > 0) {
                            ctx.fillStyle = ctx.strokeStyle;
                            ctx.font = "10px sans-serif";
                            ctx.textAlign = "right";
                            ctx.fillText(i,
                                this.graph_area_left + (i/duration) * this.graph_area_width - 5,
                                this.graph_area_top + this.graph_area_height - 5
                            );
                        }
                    }

                    // --- Draw points ---
                    const key_width = 10
                    ctx.globalAlpha = 0.5
                    for (let [point_index, point] of this.points.entries()) {
                        ctx.fillStyle = "#22bb22";
                        ctx.strokeStyle = "#008800";

                        if (this.dragState?.index == point_index){
                            ctx.fillStyle = "#ffff00"
                            ctx.strokeStyle = "#888800"
                        }

                        
                        point.y = 0
                        let [x, y] = this.toScreenCoords(point);
                        x = Math.min(x, this.graph_area_left + this.graph_area_width)
                        x -= (key_width / 2)
                        ctx.beginPath()
                        ctx.rect(x, y, key_width, -this.graph_area_height)
                        ctx.fill();
                        ctx.lineWidth = 1.5;
                        ctx.stroke();
                    }
                    ctx.globalAlpha = 1

                },

                updateCurve() {
                    this._ensureValidPoints();
                    this._updateCurveWidget();
                },

                _updateCurveWidget() {
                    if (!this.widgets) return;
                    const widget = this.widgets.find(w => w.name === "keyframe_data");
                    if (widget) {
                        const newValue = JSON.stringify({
                            keyframes: this.points
                        });
                        if (widget.value !== newValue) {
                            widget.value = newValue;
                            if (this.setDirtyCanvas) this.setDirtyCanvas(true, true);
                            if (app && app.graph) app.graph.change();
                        }
                    }
                },

                onExecute() {
                    this.updateCurve();
                },

                onConfigure(info) {
                    if (info.curve_state && Array.isArray(info.curve_state)) {
                        try {
                            this.points = info.curve_state.map(pt => ({
                                x: Number(pt.x)
                            }));
                            this._ensureValidPoints();
                            this.updateCurve();
                        } catch (e) {
                            console.error("Failed to load curve state:", e);
                        }
                    }
                },

                onSerialize(info) {
                    info.curve_state = this.points;
                },
              
            });

            const onConnectionsChange = nodeType.prototype.onConnectionsChange;
            nodeType.prototype.onConnectionsChange = function (side, slot, connect, link_info, output) {
                const r = onConnectionsChange?.apply(this, arguments);

                const existing_keyframes = this.keyframe_count
                this.keyframe_count = 0
                this.inputs.forEach((input, i) => {
                    if (this.isInputConnected(i)) this.keyframe_count += 1
                })

                if (existing_keyframes > this.keyframe_count) {
                    // we need to remove the last keyframe from the list
                    this.points.pop()
                }

                if ((existing_keyframes >= 2) && (existing_keyframes < this.keyframe_count)) {
                    this.points.forEach((point, i) => {
                        point.x = point.x * (existing_keyframes-1) / existing_keyframes 
                    })
                }

                if (this.keyframe_count > existing_keyframes) {  
                    if (existing_keyframes == 0)
                        this.points.push({x:0})
                    else
                        this.points.push({x:1})
                }                

                this.calcGraphArea()
                return r;
            }
        }
    }
});