import { app } from "../../scripts/app.js";

app.registerExtension({
    name: "InteractiveKeyframeSliders",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name === "DigbyKeyframer") {
            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function() {
                const node = this;
                
                if (onNodeCreated) {
                    onNodeCreated.apply(this, arguments);
                }

                if (!this.size) this.size = [340, 260];

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

                    this.addWidget(
                        "string",
                        "keyframe_data",
                        "",
                        curveDataCallback,
                        { multiline: false, disabled: false }
                    );
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
                this.hitRadius = 0.05;

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
                    console.log("CustomSplineSigma onMouseDown called", e, pos);
                    
                    node.calcGraphArea();
                    
                    // Check if click is inside the graph area
                    if (
                        pos[0] >= node.graph_area_left &&
                        pos[0] <= node.graph_area_left + node.graph_area_width &&
                        pos[1] >= node.graph_area_top &&
                        pos[1] <= node.graph_area_top + node.graph_area_height
                    ) {
                        console.log("Click is inside graph area");
                        
                        const graphPos = node.toGraphCoords(pos);
                        const pointIndex = node.points.findIndex(p =>
                            Math.abs(p.x - graphPos.x) < node.hitRadius
                        );
                        
                        if (pointIndex >= 0) {
                            // Delete if Shift+Left click, else drag
                            if (e.button === 0 && e.shiftKey) {
                                if (node.points.length > 2) {
                                    node.points.splice(pointIndex, 1);
                                    node.updateCurve();
                                    app.graph.change();
                                    node.setDirtyCanvas(true, true);
                                }
                                return true;
                            } else if (e.button === 0) {
                                node.dragState = {
                                    index: pointIndex,
                                    offsetX: graphPos.x - node.points[pointIndex].x
                                };
                                app.graph.change();
                                node.setDirtyCanvas(true, true);
                                return true;
                            }
                        } else if (e.button === 0) {
                            // Add new point
                            let newX = Math.max(0, Math.min(1, graphPos.x));
                            if (!node.points.some(p => Math.abs(p.x - newX) < 1e-4)) {
                                node.points.push({ x: newX });
                                node.updateCurve();
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
                        let newX = Math.max(0, Math.min(1, graphPos.x - node.dragState.offsetX));
                        const i = node.dragState.index;
                        
                        if (i > 0) newX = Math.max(node.points[i - 1].x + 1e-3, newX);
                        if (i < node.points.length - 1) newX = Math.min(node.points[i + 1].x - 1e-3, newX);
                        
                        console.log("CustomSplineSigma onMouseMove with dragState: newX = " + newX);

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
                        console.log("CustomSplineSigma onMouseUp releasing dragState");
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
                    
                    if (this.widgets && this.widgets.length) {
                        this.widgets.forEach(w => {
                            let widget_height = 30; // Default height
                            
                            if (w.type === "combo") widget_height = 30;
                            else if (w.type === "number") widget_height = 30;
                            else if (w.type === "string" && w.options && w.options.multiline) {
                                widget_height = 80; 
                            }
                            else if (w.type === "string") widget_height = 30;
                            
                            widgets_bottom += widget_height;
                        });
                        
                        widgets_bottom += 10; 
                    }
                    
                    // Reduced from 20px to 5px for less spacing
                    const extra_clearance = 5;
                    this.graph_area_top = widgets_bottom + extra_clearance;
                    
                    // Calculate available space for graph
                    this.graph_area_height = this.size[1] - this.graph_area_top - this.graph_bottom_margin;
                    this.graph_area_width = this.size[0] - this.graph_side_margin * 2;
                    this.graph_area_left = this.graph_side_margin;
                    
                    // Ensure minimum graph height
                    const min_graph_height = 10;
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
                            x: Math.max(0, Math.min(1, p.x))
                        }))
                        .sort((a, b) => a.x - b.x);
                    this.points = this.points.filter((pt, idx, arr) =>
                        idx === 0 || pt.x !== arr[idx - 1].x
                    );
                    /*
                    if (this.points.length < 2) {
                        this.points = [
                            { x: 0 },
                            { x: 0.5 },
                            { x: 1 }
                        ];
                    }
                        */
                },

                toScreenCoords(point) {
                    this.calcGraphArea();
                    return [
                        this.graph_area_left + point.x * this.graph_area_width,
                        this.graph_area_top + (1 - point.y) * this.graph_area_height
                    ];
                },

                toGraphCoords(pos) {
                    this.calcGraphArea();
                    return {
                        x: Math.max(0, Math.min(1, (pos[0] - this.graph_area_left) / this.graph_area_width))
                    };
                },

                onDrawForeground(ctx) {
                    this.calcGraphArea();
                    this._ensureValidPoints();
                    this.updateCurve();

                    // --- White background for the graph area ---
                    ctx.fillStyle = "#fff";
                    ctx.fillRect(
                        this.graph_area_left,
                        this.graph_area_top,
                        this.graph_area_width,
                        this.graph_area_height
                    );

                    // --- Draw grid ---
                    ctx.strokeStyle = "#eee";
                    ctx.lineWidth = 1;
                    ctx.beginPath();
                    for (let i = 0.25; i < 1; i += 0.25) {
                        // Vertical grid lines
                        let x = this.graph_area_left + i * this.graph_area_width;
                        ctx.moveTo(x, this.graph_area_top);
                        ctx.lineTo(x, this.graph_area_top + this.graph_area_height);
                        // Horizontal grid lines
                        let y = this.graph_area_top + i * this.graph_area_height;
                        ctx.moveTo(this.graph_area_left, y);
                        ctx.lineTo(this.graph_area_left + this.graph_area_width, y);
                    }
                    ctx.stroke();

                    // --- Draw axes ---
                    ctx.strokeStyle = "#aaa";
                    ctx.beginPath();
                    // X axis (bottom)
                    ctx.moveTo(this.graph_area_left, this.graph_area_top + this.graph_area_height);
                    ctx.lineTo(this.graph_area_left + this.graph_area_width, this.graph_area_top + this.graph_area_height);
                    // Y axis (left)
                    ctx.moveTo(this.graph_area_left, this.graph_area_top + this.graph_area_height);
                    ctx.lineTo(this.graph_area_left, this.graph_area_top);
                    ctx.stroke();

                    // --- Draw points ---
                    const key_width = 10
                    ctx.fillStyle = "#FF5555";
                    for (let point of this.points) {
                        point.y = 0
                        let [x, y] = this.toScreenCoords(point);
                        x = Math.min(x, this.graph_area_left + this.graph_area_width - key_width)
                        ctx.beginPath()
                        ctx.rect(x, y, key_width, -this.graph_area_height)
                        ctx.fill();
                        ctx.strokeStyle = "#880000";
                        ctx.lineWidth = 1.5;
                        ctx.stroke();
                    }

                    // --- Draw user instruction just below the graph area ---
                    ctx.fillStyle = "#222";
                    ctx.font = "11px sans-serif";
                    ctx.fillText(
                        "Shift+Click to delete point",
                        this.graph_area_left + 5,
                        this.graph_area_top + this.graph_area_height + 16
                    );
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

                if (existing_keyframes < this.keyframe_count) {
                    this.points.forEach((point, i) => {
                        point.x = point.x * existing_keyframes / this.keyframe_count
                    })
                    this.points.push({x:1})
                    // we need to add a new keyframe to the end
                }
                
                // Your slot change logic here
                console.log("Connection changed!", { side, slot, connect, link_info });
                return r;
            }
        }
    }
});