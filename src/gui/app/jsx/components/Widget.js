"use strict";

var React = require("react");

var Icon   = require("./Icon");


var Widget = React.createClass({
  render: function() {
    var divStyle = {
      position: "absolute",
      left: this.props.positionX + "px",
      top: this.props.positionY + "px"
    };

    return (
      <div className={"widget " + this.props.size} style={divStyle}>
        <div className="widget-content">
          { this.props.children }
        </div>
      </div>
    );
  }
});

module.exports = Widget;

      // Widget header removed for now
      //  <header>
      //    <span className="widgetTitle">{this.props.title} <Icon glyph="gear" icoSize="lg" /></span>
      //  </header>